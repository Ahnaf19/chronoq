"""Redis sorted set SJF queue."""

import json
from datetime import UTC, datetime

from redis.asyncio import Redis


class TaskQueue:
    """Priority queue backed by Redis sorted set (lowest score = shortest job first)."""

    def __init__(self, redis_client: Redis, queue_key: str, task_hash_prefix: str) -> None:
        self._redis = redis_client
        self._queue_key = queue_key
        self._prefix = task_hash_prefix

    async def enqueue(
        self,
        task_id: str,
        task_type: str,
        payload_size: int,
        predicted_ms: float,
        metadata: dict | None = None,
    ) -> None:
        """Add a task to the queue with predicted_ms as SJF score."""
        task_data = {
            "task_id": task_id,
            "task_type": task_type,
            "payload_size": str(payload_size),
            "predicted_ms": str(predicted_ms),
            "metadata": json.dumps(metadata or {}),
            "status": "pending",
            "submitted_at": datetime.now(UTC).isoformat(),
        }
        pipe = self._redis.pipeline()
        pipe.hset(f"{self._prefix}{task_id}", mapping=task_data)
        pipe.zadd(self._queue_key, {task_id: predicted_ms})
        await pipe.execute()

    async def dequeue(self) -> dict | None:
        """Pop the shortest predicted job (lowest score)."""
        result = await self._redis.zpopmin(self._queue_key, count=1)
        if not result:
            return None
        task_id, _score = result[0]
        if isinstance(task_id, bytes):
            task_id = task_id.decode()
        task_data = await self._redis.hgetall(f"{self._prefix}{task_id}")
        if not task_data:
            return None
        return self._decode_hash(task_data)

    async def length(self) -> int:
        """Number of tasks in the queue."""
        return await self._redis.zcard(self._queue_key)

    async def peek(self, n: int = 10) -> list[dict]:
        """View top N tasks in queue order without removing them."""
        members = await self._redis.zrange(self._queue_key, 0, n - 1, withscores=True)
        tasks = []
        for member, score in members:
            if isinstance(member, bytes):
                member = member.decode()
            task_data = await self._redis.hgetall(f"{self._prefix}{member}")
            if task_data:
                task = self._decode_hash(task_data)
                task["queue_score"] = score
                tasks.append(task)
        return tasks

    async def update_status(self, task_id: str, status: str, **extra: str) -> None:
        """Update task status and optional extra fields."""
        mapping = {"status": status, **extra}
        await self._redis.hset(f"{self._prefix}{task_id}", mapping=mapping)

    async def get_task(self, task_id: str) -> dict | None:
        """Get task details by ID."""
        data = await self._redis.hgetall(f"{self._prefix}{task_id}")
        if not data:
            return None
        return self._decode_hash(data)

    @staticmethod
    def _decode_hash(data: dict) -> dict:
        """Decode bytes keys/values from Redis hash."""
        decoded = {}
        for k, v in data.items():
            key = k.decode() if isinstance(k, bytes) else k
            val = v.decode() if isinstance(v, bytes) else v
            decoded[key] = val
        return decoded

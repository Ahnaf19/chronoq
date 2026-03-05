"""Demo script: submit tasks, watch SJF scheduling and model promotion in action."""

import asyncio
import random
import time

import httpx

BASE_URL = "http://localhost:8000"

TASK_TYPES = ["resize_image", "send_email", "generate_report", "compress_file", "run_inference"]


async def submit_tasks(client: httpx.AsyncClient, count: int = 200) -> list[dict]:
    """Submit a batch of random tasks."""
    tasks = []
    for _ in range(count):
        task_type = random.choice(TASK_TYPES)
        payload_size = random.randint(100, 5000)
        resp = await client.post(
            f"{BASE_URL}/tasks",
            json={"task_type": task_type, "payload_size": payload_size},
        )
        tasks.append(resp.json())
    return tasks


def print_metrics(metrics: dict, elapsed: float) -> None:
    """Print a formatted metrics snapshot."""
    pred = metrics.get("prediction", {})
    workers = metrics.get("workers", [])
    total_completed = sum(w.get("tasks_completed", 0) for w in workers)
    avg_util = (
        sum(w.get("utilization_percent", 0) for w in workers) / len(workers) if workers else 0
    )

    print(f"\n--- {elapsed:.0f}s elapsed ---")
    print(f"  Queue depth:     {metrics.get('queue_depth', '?')}")
    print(f"  Model type:      {pred.get('model_type', '?')}")
    print(f"  Model version:   {pred.get('model_version', '?')}")
    print(f"  Total records:   {pred.get('total_records', '?')}")
    print(f"  Tasks completed: {total_completed}")
    print(f"  Avg utilization: {avg_util:.1f}%")


async def main() -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("Submitting 200 tasks...")
        start = time.time()
        tasks = await submit_tasks(client, count=200)
        print(f"Submitted {len(tasks)} tasks in {time.time() - start:.1f}s")

        # Poll metrics until queue is drained
        while True:
            await asyncio.sleep(2.0)
            elapsed = time.time() - start

            resp = await client.get(f"{BASE_URL}/metrics")
            if resp.status_code != 200:
                print(f"Metrics fetch failed: {resp.status_code}")
                continue

            metrics = resp.json()
            print_metrics(metrics, elapsed)

            if metrics.get("queue_depth", 1) == 0:
                print("\nQueue drained!")
                break

            if elapsed > 300:
                print("\nTimeout after 5 minutes")
                break

        # Final predictions comparison
        resp = await client.get(f"{BASE_URL}/metrics/predictions")
        if resp.status_code == 200:
            predictions = resp.json()
            if predictions:
                print(f"\n--- Prediction Accuracy ({len(predictions)} samples) ---")
                print(f"{'Task Type':<20} {'Predicted':>10} {'Actual':>10} {'Error':>10}")
                print("-" * 55)
                for p in predictions[-20:]:
                    print(
                        f"{p['task_type']:<20} {p['predicted_ms']:>10.0f} "
                        f"{p['actual_ms']:>10.0f} {p['error_ms']:>10.0f}"
                    )


if __name__ == "__main__":
    asyncio.run(main())

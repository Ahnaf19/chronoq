"""Simulated task definitions with characteristic time profiles."""

import asyncio
import random

TASK_REGISTRY: dict[str, dict] = {
    "resize_image": {
        "base_ms": 300,
        "variance": 80,
        "payload_factor": 0.05,
    },
    "send_email": {
        "base_ms": 150,
        "variance": 30,
        "payload_factor": 0.01,
    },
    "generate_report": {
        "base_ms": 2000,
        "variance": 500,
        "payload_factor": 0.1,
    },
    "compress_file": {
        "base_ms": 800,
        "variance": 200,
        "payload_factor": 0.08,
    },
    "run_inference": {
        "base_ms": 1500,
        "variance": 400,
        "payload_factor": 0.12,
    },
}


async def simulate_task(task_type: str, payload_size: int) -> float:
    """Simulate task execution. Returns actual duration in ms."""
    profile = TASK_REGISTRY.get(task_type)
    if profile is None:
        actual_ms = 500.0 + random.gauss(0, 100)
    else:
        actual_ms = (
            profile["base_ms"]
            + payload_size * profile["payload_factor"]
            + random.gauss(0, profile["variance"])
        )
    actual_ms = max(1.0, actual_ms)
    await asyncio.sleep(actual_ms / 1000.0)
    return actual_ms

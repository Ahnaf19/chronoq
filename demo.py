"""Demo script: submit tasks in waves, watch SJF scheduling and model promotion in action."""

import asyncio
import random
import time

import httpx

BASE_URL = "http://localhost:8000"

TASK_TYPES = ["resize_image", "send_email", "generate_report", "compress_file", "run_inference"]

# Submit in 4 waves so later waves benefit from the trained model
WAVES = [
    {"count": 60, "label": "Wave 1 (cold start)"},
    {"count": 60, "label": "Wave 2 (heuristic learning)"},
    {"count": 40, "label": "Wave 3 (post-promotion)"},
    {"count": 40, "label": "Wave 4 (gradient boosting)"},
]


async def submit_tasks(client: httpx.AsyncClient, count: int) -> list[dict]:
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


async def wait_for_queue_below(client: httpx.AsyncClient, threshold: int, start: float) -> dict:
    """Poll until queue depth drops below threshold. Returns last metrics."""
    while True:
        await asyncio.sleep(2.0)
        resp = await client.get(f"{BASE_URL}/metrics")
        metrics = resp.json()
        print_metrics(metrics, time.time() - start)
        if metrics.get("queue_depth", threshold + 1) <= threshold:
            return metrics
        if time.time() - start > 300:
            print("\nTimeout after 5 minutes")
            return metrics


async def main() -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        start = time.time()
        total_submitted = 0

        for wave in WAVES:
            count = wave["count"]
            label = wave["label"]
            print(f"\n{'=' * 55}")
            print(f"  {label}: submitting {count} tasks...")
            print(f"{'=' * 55}")
            t0 = time.time()
            await submit_tasks(client, count=count)
            total_submitted += count
            print(
                f"  Submitted {count} tasks in {time.time() - t0:.1f}s (total: {total_submitted})"
            )

            # Wait until queue is nearly drained before next wave
            # This gives the model time to learn from completions
            await wait_for_queue_below(client, threshold=5, start=start)

        # Wait for final drain
        print(f"\n{'=' * 55}")
        print("  Waiting for queue to fully drain...")
        print(f"{'=' * 55}")
        while True:
            await asyncio.sleep(2.0)
            resp = await client.get(f"{BASE_URL}/metrics")
            metrics = resp.json()
            print_metrics(metrics, time.time() - start)
            if metrics.get("queue_depth", 1) == 0:
                print("\nQueue drained!")
                break
            if time.time() - start > 300:
                print("\nTimeout after 5 minutes")
                break

        # Final predictions comparison
        resp = await client.get(f"{BASE_URL}/metrics/predictions?n=200")
        if resp.status_code == 200:
            predictions = resp.json()
            if predictions:
                # Split into early (heuristic) vs late (gradient boosting) predictions
                mid = len(predictions) // 2
                early = predictions[:mid]
                late = predictions[mid:]

                early_mae = sum(p["error_ms"] for p in early) / len(early) if early else 0
                late_mae = sum(p["error_ms"] for p in late) / len(late) if late else 0

                print(f"\n{'=' * 65}")
                print(f"  Prediction Accuracy Summary ({len(predictions)} total samples)")
                print(f"{'=' * 65}")
                print(f"  Early predictions MAE (heuristic):          {early_mae:>8.0f} ms")
                print(f"  Late predictions MAE  (gradient boosting):  {late_mae:>8.0f} ms")
                improvement = ((early_mae - late_mae) / early_mae * 100) if early_mae > 0 else 0
                print(f"  Improvement:                                {improvement:>7.1f}%")

                print("\n--- Last 20 predictions (gradient boosting) ---")
                print(f"{'Task Type':<20} {'Predicted':>10} {'Actual':>10} {'Error':>10}")
                print("-" * 55)
                for p in predictions[-20:]:
                    print(
                        f"{p['task_type']:<20} {p['predicted_ms']:>10.0f} "
                        f"{p['actual_ms']:>10.0f} {p['error_ms']:>10.0f}"
                    )


if __name__ == "__main__":
    asyncio.run(main())

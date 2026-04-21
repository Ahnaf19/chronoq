"""Tests for the auto-retrain trigger fix (count_since by datetime, not version string)."""

import pytest
from chronoq_ranker import RankerConfig, TaskRanker
from chronoq_ranker.storage.memory import MemoryStore


@pytest.fixture()
def low_threshold_config():
    return RankerConfig(
        cold_start_threshold=10,
        retrain_every_n=5,
        min_groups=2,
        allow_degrade=True,
    )


def test_auto_retrain_fires_multiple_times(low_threshold_config):
    """Auto-retrain must fire on every threshold crossing, not just the first."""
    store = MemoryStore()
    ranker = TaskRanker(config=low_threshold_config, storage=store)

    retrain_calls = []
    original_retrain = ranker.retrain

    def counting_retrain():
        result = original_retrain()
        retrain_calls.append(result)
        return result

    ranker.retrain = counting_retrain

    # First batch: exceed retrain_every_n=5
    for i in range(6):
        ranker.record(task_type="resize", payload_size=100 + i, actual_ms=float(100 + i * 10))

    first_count = len(retrain_calls)
    assert first_count >= 1, "Auto-retrain should fire at least once after 6 records"

    # Second batch: exceed the threshold again from the new cutoff
    for i in range(6):
        ranker.record(task_type="resize", payload_size=200 + i, actual_ms=float(200 + i * 10))

    second_count = len(retrain_calls)
    assert second_count > first_count, (
        "Auto-retrain must fire again after a second threshold crossing. "
        f"Fired {first_count} time(s) after first batch, still {second_count} after second. "
        "This is the count_since() bug: if counting by version string, it returns 0 "
        "for new records that have the new version and retrain never fires again."
    )


def test_count_since_resets_after_retrain(low_threshold_config):
    """After a retrain, count_since should count only records written after that retrain."""
    # Disable auto-retrain so we can call retrain manually and inspect state.
    cfg = RankerConfig(
        cold_start_threshold=10,
        retrain_every_n=9999,
        min_groups=2,
        allow_degrade=True,
    )
    ranker2 = TaskRanker(config=cfg, storage=MemoryStore())

    # Save 3 records before retrain
    for i in range(3):
        ranker2._store.save(
            __import__("chronoq_ranker").schemas.TaskRecord(
                task_type="t",
                payload_size=i,
                actual_ms=float(i + 1),
            )
        )

    epoch = ranker2._last_retrain_at
    assert ranker2._store.count_since(epoch) == 3

    # Simulate a retrain by calling retrain() explicitly (degrades to heuristic; not enough groups)
    ranker2.retrain()
    new_cutoff = ranker2._last_retrain_at
    assert new_cutoff > epoch, "_last_retrain_at must advance after retrain()"

    # Records written before the retrain should NOT be counted after the new cutoff
    assert ranker2._store.count_since(new_cutoff) == 0

    # New records after the retrain should be counted
    ranker2._store.save(
        __import__("chronoq_ranker").schemas.TaskRecord(
            task_type="t", payload_size=99, actual_ms=100.0
        )
    )
    assert ranker2._store.count_since(new_cutoff) == 1

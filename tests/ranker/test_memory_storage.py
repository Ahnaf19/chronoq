"""Tests for MemoryStore."""

from datetime import UTC, datetime, timedelta

from chronoq_ranker.schemas import TaskRecord
from chronoq_ranker.storage.memory import MemoryStore

_EPOCH = datetime.min.replace(tzinfo=UTC)


def test_save_and_get_all():
    store = MemoryStore()
    r = TaskRecord(task_type="test", payload_size=10, actual_ms=100.0)
    store.save(r)
    assert store.get_all() == [r]


def test_get_by_type():
    store = MemoryStore()
    store.save(TaskRecord(task_type="a", payload_size=10, actual_ms=100.0))
    store.save(TaskRecord(task_type="b", payload_size=20, actual_ms=200.0))
    store.save(TaskRecord(task_type="a", payload_size=30, actual_ms=300.0))
    assert len(store.get_by_type("a")) == 2
    assert len(store.get_by_type("b")) == 1
    assert len(store.get_by_type("c")) == 0


def test_count():
    store = MemoryStore()
    assert store.count() == 0
    store.save(TaskRecord(task_type="x", payload_size=1, actual_ms=10.0))
    store.save(TaskRecord(task_type="y", payload_size=2, actual_ms=20.0))
    assert store.count() == 2


def test_count_since():
    store = MemoryStore()
    t0 = datetime.now(UTC) - timedelta(seconds=10)
    t1 = datetime.now(UTC) - timedelta(seconds=5)
    t2 = datetime.now(UTC)
    store.save(TaskRecord(task_type="a", payload_size=1, actual_ms=10.0, recorded_at=t0))
    store.save(TaskRecord(task_type="b", payload_size=2, actual_ms=20.0, recorded_at=t1))
    store.save(TaskRecord(task_type="c", payload_size=3, actual_ms=30.0, recorded_at=t2))

    # Cutoff before t0 → all 3 records after
    assert store.count_since(_EPOCH) == 3
    # Cutoff between t0 and t1 → 2 records (t1 and t2)
    cutoff = t0 + timedelta(seconds=1)
    assert store.count_since(cutoff) == 2
    # Cutoff at t2 → 0 records strictly after
    assert store.count_since(t2) == 0


def test_empty_store():
    store = MemoryStore()
    assert store.get_all() == []
    assert store.get_by_type("any") == []
    assert store.count() == 0
    assert store.count_since(_EPOCH) == 0

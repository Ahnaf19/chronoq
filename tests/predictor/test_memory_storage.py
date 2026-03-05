"""Tests for MemoryStore."""

from chronoq_predictor.schemas import TaskRecord
from chronoq_predictor.storage.memory import MemoryStore


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
    store.save(
        TaskRecord(task_type="a", payload_size=1, actual_ms=10.0, model_version_at_record="v1")
    )
    store.save(
        TaskRecord(task_type="b", payload_size=2, actual_ms=20.0, model_version_at_record="v2")
    )
    store.save(
        TaskRecord(task_type="c", payload_size=3, actual_ms=30.0, model_version_at_record="v2")
    )
    assert store.count_since("v1") == 1
    assert store.count_since("v2") == 2
    assert store.count_since("v3") == 0


def test_empty_store():
    store = MemoryStore()
    assert store.get_all() == []
    assert store.get_by_type("any") == []
    assert store.count() == 0
    assert store.count_since("v1") == 0

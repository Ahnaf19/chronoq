"""Tests for SqliteStore."""

from datetime import UTC, datetime, timedelta

from chronoq_ranker.schemas import TaskRecord
from chronoq_ranker.storage.sqlite import SqliteStore

_EPOCH = datetime.min.replace(tzinfo=UTC)


def test_save_and_get_all(tmp_path):
    store = SqliteStore(f"sqlite:///{tmp_path}/test.db")
    r = TaskRecord(task_type="test", payload_size=10, actual_ms=100.0)
    store.save(r)
    records = store.get_all()
    assert len(records) == 1
    assert records[0].task_type == "test"
    assert records[0].actual_ms == 100.0


def test_get_by_type(tmp_path):
    store = SqliteStore(f"sqlite:///{tmp_path}/test.db")
    store.save(TaskRecord(task_type="a", payload_size=10, actual_ms=100.0))
    store.save(TaskRecord(task_type="b", payload_size=20, actual_ms=200.0))
    store.save(TaskRecord(task_type="a", payload_size=30, actual_ms=300.0))
    assert len(store.get_by_type("a")) == 2
    assert len(store.get_by_type("b")) == 1


def test_count(tmp_path):
    store = SqliteStore(f"sqlite:///{tmp_path}/test.db")
    assert store.count() == 0
    store.save(TaskRecord(task_type="x", payload_size=1, actual_ms=10.0))
    assert store.count() == 1


def test_count_since(tmp_path):
    store = SqliteStore(f"sqlite:///{tmp_path}/test.db")
    t0 = datetime.now(UTC) - timedelta(seconds=10)
    t1 = datetime.now(UTC) - timedelta(seconds=5)
    t2 = datetime.now(UTC)
    store.save(TaskRecord(task_type="a", payload_size=1, actual_ms=10.0, recorded_at=t0))
    store.save(TaskRecord(task_type="b", payload_size=2, actual_ms=20.0, recorded_at=t1))
    store.save(TaskRecord(task_type="c", payload_size=3, actual_ms=30.0, recorded_at=t2))

    assert store.count_since(_EPOCH) == 3
    cutoff = t0 + timedelta(seconds=1)
    assert store.count_since(cutoff) == 2
    assert store.count_since(t2) == 0


def test_persistence_across_instances(tmp_path):
    db_path = f"sqlite:///{tmp_path}/persist.db"
    store1 = SqliteStore(db_path)
    store1.save(TaskRecord(task_type="test", payload_size=10, actual_ms=100.0))
    assert store1.count() == 1

    store2 = SqliteStore(db_path)
    assert store2.count() == 1
    records = store2.get_all()
    assert records[0].task_type == "test"


def test_metadata_json_roundtrip(tmp_path):
    store = SqliteStore(f"sqlite:///{tmp_path}/test.db")
    meta = {"worker": "w-1", "queue_depth": 5, "nested": {"key": "value"}}
    store.save(TaskRecord(task_type="test", payload_size=10, actual_ms=100.0, metadata=meta))
    records = store.get_all()
    assert records[0].metadata == meta

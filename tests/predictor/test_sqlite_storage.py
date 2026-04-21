"""Tests for SqliteStore."""

from chronoq_ranker.schemas import TaskRecord
from chronoq_ranker.storage.sqlite import SqliteStore


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
    store.save(
        TaskRecord(task_type="a", payload_size=1, actual_ms=10.0, model_version_at_record="v1")
    )
    store.save(
        TaskRecord(task_type="b", payload_size=2, actual_ms=20.0, model_version_at_record="v2")
    )
    assert store.count_since("v1") == 1
    assert store.count_since("v2") == 1
    assert store.count_since("v3") == 0


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

"""SQLite telemetry storage backend."""

import json
import sqlite3
import threading
from datetime import UTC, datetime

from chronoq_ranker.schemas import TaskRecord
from chronoq_ranker.storage.base import TelemetryStore

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    payload_size INTEGER,
    actual_ms REAL NOT NULL,
    metadata_json TEXT,
    recorded_at TEXT NOT NULL,
    model_version_at_record TEXT
)
"""


class SqliteStore(TelemetryStore):
    """SQLite-backed persistent telemetry storage."""

    def __init__(self, uri: str) -> None:
        self._db_path = uri.removeprefix("sqlite:///")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    def save(self, record: TaskRecord) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO telemetry "
                "(task_type, payload_size, actual_ms, metadata_json, recorded_at, "
                "model_version_at_record) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.task_type,
                    record.payload_size,
                    record.actual_ms,
                    json.dumps(record.metadata),
                    record.recorded_at.isoformat(),
                    record.model_version_at_record,
                ),
            )
            self._conn.commit()

    def get_all(self) -> list[TaskRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT task_type, payload_size, actual_ms, metadata_json, "
                "recorded_at, model_version_at_record FROM telemetry"
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_by_type(self, task_type: str) -> list[TaskRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT task_type, payload_size, actual_ms, metadata_json, "
                "recorded_at, model_version_at_record FROM telemetry WHERE task_type = ?",
                (task_type,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()
        return row[0]

    def count_since(self, model_version: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM telemetry WHERE model_version_at_record = ?",
                (model_version,),
            ).fetchone()
        return row[0]

    @staticmethod
    def _row_to_record(row: tuple) -> TaskRecord:
        task_type, payload_size, actual_ms, metadata_json, recorded_at, model_version = row
        return TaskRecord(
            task_type=task_type,
            payload_size=payload_size,
            actual_ms=actual_ms,
            metadata=json.loads(metadata_json) if metadata_json else {},
            recorded_at=datetime.fromisoformat(recorded_at).replace(tzinfo=UTC),
            model_version_at_record=model_version or "",
        )

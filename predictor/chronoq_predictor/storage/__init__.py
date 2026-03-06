"""Telemetry storage backends."""

from chronoq_predictor.storage.base import TelemetryStore
from chronoq_predictor.storage.memory import MemoryStore
from chronoq_predictor.storage.sqlite import SqliteStore

__all__ = ["TelemetryStore", "MemoryStore", "SqliteStore", "create_store"]


def create_store(uri: str) -> TelemetryStore:
    """Factory: create a storage backend from a URI string."""
    if uri == "memory://":
        return MemoryStore()
    if uri.startswith("sqlite:///"):
        return SqliteStore(uri)
    raise ValueError(f"Unsupported storage URI: {uri}")

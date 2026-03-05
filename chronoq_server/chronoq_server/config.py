"""Server configuration with environment variable overrides."""

import os
from dataclasses import dataclass


@dataclass
class ServerConfig:
    """Configuration for the Chronoq server."""

    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    worker_count: int = int(os.environ.get("CHRONOQ_WORKER_COUNT", "4"))
    queue_key: str = os.environ.get("CHRONOQ_QUEUE_KEY", "chronoq:tasks")
    task_hash_prefix: str = os.environ.get("CHRONOQ_TASK_PREFIX", "chronoq:task:")
    predictor_storage: str = os.environ.get(
        "CHRONOQ_PREDICTOR_STORAGE", "sqlite:///chronoq_telemetry.db"
    )
    cold_start_threshold: int = int(os.environ.get("CHRONOQ_COLD_START", "50"))
    retrain_every_n: int = int(os.environ.get("CHRONOQ_RETRAIN_EVERY", "100"))

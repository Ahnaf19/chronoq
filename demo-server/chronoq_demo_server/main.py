"""FastAPI application with lifespan management."""

from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from chronoq_ranker import PredictorConfig, TaskPredictor
from fastapi import FastAPI
from loguru import logger

from chronoq_demo_server.api.metrics import PredictionTracker
from chronoq_demo_server.api.metrics import router as metrics_router
from chronoq_demo_server.api.tasks import router as tasks_router
from chronoq_demo_server.config import ServerConfig
from chronoq_demo_server.core.queue import TaskQueue
from chronoq_demo_server.core.scheduler import Scheduler
from chronoq_demo_server.core.worker import WorkerPool


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and tear down server components."""
    config = ServerConfig()

    # Redis
    redis_client = aioredis.from_url(config.redis_url, decode_responses=True)
    logger.info("Connected to Redis at {}", config.redis_url)

    # Predictor
    predictor_config = PredictorConfig(
        storage_uri=config.predictor_storage,
        cold_start_threshold=config.cold_start_threshold,
        retrain_every_n=config.retrain_every_n,
    )
    predictor = TaskPredictor(config=predictor_config)

    # Core components
    queue = TaskQueue(redis_client, config.queue_key, config.task_hash_prefix)
    scheduler = Scheduler(predictor, queue)
    prediction_tracker = PredictionTracker()
    worker_pool = WorkerPool(
        queue,
        scheduler,
        worker_count=config.worker_count,
        prediction_tracker=prediction_tracker,
    )

    # Store on app state
    app.state.redis = redis_client
    app.state.queue = queue
    app.state.scheduler = scheduler
    app.state.worker_pool = worker_pool
    app.state.prediction_tracker = prediction_tracker

    await worker_pool.start()

    yield

    await worker_pool.stop()
    await redis_client.aclose()
    logger.info("Chronoq server shut down")


app = FastAPI(title="Chronoq", version="0.1.0", lifespan=lifespan)
app.include_router(tasks_router)
app.include_router(metrics_router)

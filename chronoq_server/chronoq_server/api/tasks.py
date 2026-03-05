"""Task submission and status API endpoints."""

import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskSubmission(BaseModel):
    """Request body for submitting a single task."""

    task_type: str
    payload_size: int
    metadata: dict | None = None


class TaskResponse(BaseModel):
    """Response after submitting a task."""

    task_id: str
    predicted_ms: float
    confidence: float
    model_type: str


class BatchSubmission(BaseModel):
    """Request body for submitting multiple tasks."""

    tasks: list[TaskSubmission]


@router.post("", response_model=TaskResponse)
async def submit_task(submission: TaskSubmission, request: Request) -> TaskResponse:
    """Submit a single task for SJF-scheduled execution."""
    scheduler = request.app.state.scheduler
    task_id = str(uuid.uuid4())
    prediction = await scheduler.score_and_enqueue(
        task_id=task_id,
        task_type=submission.task_type,
        payload_size=submission.payload_size,
        metadata=submission.metadata,
    )
    return TaskResponse(
        task_id=task_id,
        predicted_ms=prediction.estimated_ms,
        confidence=prediction.confidence,
        model_type=prediction.model_type,
    )


@router.post("/batch", response_model=list[TaskResponse])
async def submit_batch(batch: BatchSubmission, request: Request) -> list[TaskResponse]:
    """Submit multiple tasks in one request."""
    scheduler = request.app.state.scheduler
    responses = []
    for sub in batch.tasks:
        task_id = str(uuid.uuid4())
        prediction = await scheduler.score_and_enqueue(
            task_id=task_id,
            task_type=sub.task_type,
            payload_size=sub.payload_size,
            metadata=sub.metadata,
        )
        responses.append(
            TaskResponse(
                task_id=task_id,
                predicted_ms=prediction.estimated_ms,
                confidence=prediction.confidence,
                model_type=prediction.model_type,
            )
        )
    return responses


@router.get("/{task_id}")
async def get_task(task_id: str, request: Request) -> dict:
    """Get task status and details."""
    queue = request.app.state.queue
    task = await queue.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("")
async def get_queue(request: Request) -> list[dict]:
    """Get current queue snapshot in SJF order."""
    queue = request.app.state.queue
    return await queue.peek(n=50)

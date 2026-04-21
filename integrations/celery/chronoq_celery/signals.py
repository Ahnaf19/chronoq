"""Celery signal wiring for LearnedScheduler.

attach_signals() connects task_prerun, task_success, and task_failure to the
scheduler's registry and completion recording methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from celery.signals import task_failure, task_prerun, task_success

if TYPE_CHECKING:
    from celery import Celery

    from .scheduler import LearnedScheduler


def attach_signals(app: Celery, scheduler: LearnedScheduler) -> None:
    """Wire Celery signals to the given LearnedScheduler instance.

    Args:
        app:       The Celery application.
        scheduler: The scheduler to attach signals to.
    """

    @task_prerun.connect
    def on_task_prerun(sender=None, task_id=None, task=None, args=None, kwargs=None, **extra):
        task_type = (kwargs or {}).get("task_type", getattr(sender, "name", "unknown"))
        payload_size = int((kwargs or {}).get("payload_size", 0))
        if task_id:
            scheduler.record_start(task_id, task_type, payload_size)

    @task_success.connect
    def on_task_success(sender=None, result=None, **extra):
        task_id = getattr(sender.request, "id", None) if sender else None
        task_type = getattr(sender, "name", "unknown") if sender else "unknown"
        payload_size = int(getattr(sender.request, "kwargs", {}).get("payload_size", 0))
        if task_id:
            scheduler.record_completion(task_id, task_type, payload_size)
        if scheduler.mode == "active":
            scheduler.dispatch_next()

    @task_failure.connect
    def on_task_failure(sender=None, task_id=None, **extra):
        if task_id:
            scheduler.cleanup_registry(task_id)

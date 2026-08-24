"""Celery application.

Configured to degrade gracefully: with no ``REDIS_URL`` the app runs in eager
mode, so ``/extract-async`` still works (synchronously) and the tests do not
need a broker.  Set ``REDIS_URL`` and start a worker to get real queueing.

Task settings worth noting:

* ``acks_late`` + ``reject_on_worker_lost`` -- an extraction that dies mid-flight
  is redelivered rather than silently lost.
* ``task_time_limit`` -- a wedged LLM call must not hold a worker slot forever.
* ``worker_prefetch_multiplier=1`` -- these tasks are long and uneven, so
  prefetching just makes one worker hoard the queue.
"""

from __future__ import annotations

import logging

from celery import Celery

from app.config import settings

logger = logging.getLogger(__name__)

broker = settings.redis_url or "memory://"
backend = settings.redis_url or "cache+memory://"

celery_app = Celery("clinical_evidence", broker=broker, backend=backend)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=900,
    task_soft_time_limit=840,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=200,
    result_expires=60 * 60 * 24,
    task_always_eager=settings.celery_task_always_eager or not settings.redis_url,
    task_eager_propagates=False,
)

if not settings.redis_url:
    logger.info("No REDIS_URL configured; Celery runs tasks eagerly in-process.")

import app.workers.tasks  # noqa: E402,F401  (register tasks on import)

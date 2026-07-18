"""Очередь задач (RQ поверх Redis). Бот кладёт, воркер разбирает."""

from redis import Redis
from rq import Queue

from bot.config import REDIS_URL, QUEUE_NAME, JOB_TIMEOUT

_redis = Redis.from_url(REDIS_URL)
_queue = Queue(QUEUE_NAME, connection=_redis)


def get_redis() -> Redis:
    return _redis


def enqueue(task_name: str, *args) -> int:
    """Ставит задачу, возвращает позицию в очереди (1 = следующая)."""
    _queue.enqueue(f'worker.tasks.{task_name}', *args,
                   job_timeout=JOB_TIMEOUT, result_ttl=3600, failure_ttl=3600)
    return _queue.count

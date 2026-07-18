"""Точка входа воркера: один процесс RQ, разбирает очередь по одной задаче."""

import logging

from redis import Redis
from rq import Queue, SimpleWorker

from bot import db
from bot.config import QUEUE_NAME, REDIS_URL, ensure_dirs

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(name)s: %(message)s')


def main():
    ensure_dirs()
    db.init_db()
    conn = Redis.from_url(REDIS_URL)
    # SimpleWorker (без форка на задачу): embedded Qdrant держит файловый лок,
    # а ленивый Grader переживает задачи — один процесс на всё
    worker = SimpleWorker([Queue(QUEUE_NAME, connection=conn)], connection=conn)
    logging.info('Воркер запущен, очередь: %s', QUEUE_NAME)
    worker.work()


if __name__ == '__main__':
    main()

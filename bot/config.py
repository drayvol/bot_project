"""Общий конфиг бота и воркера. Все значения — из окружения."""

import os

BOT_TOKEN = os.environ['BOT_TOKEN']
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

DATA_DIR = os.environ.get('DATA_DIR', 'storage')
PHOTOS_DIR = os.path.join(DATA_DIR, 'photos')
DB_PATH = os.path.join(DATA_DIR, 'bot.sqlite3')

QUEUE_NAME = 'grading'
# grade() внутри ретраится с паузами до 80с и таймаутом 180с на запрос —
# даём задаче запас, иначе RQ убьёт её посреди ретраев
JOB_TIMEOUT = 1200

SIMILAR_TOP_K = 3


def ensure_dirs():
    os.makedirs(PHOTOS_DIR, exist_ok=True)

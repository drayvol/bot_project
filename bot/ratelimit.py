"""Общий лимитер запросов к Gemini для всех воркеров.

Один воркер сам по себе не пробьёт 15 rpm (задачи последовательные, в коде
паузы), но при --scale worker=N лимит общий на аккаунт — поэтому счётчик
живёт в Redis, а не в процессе.

Fixed window: счётчик на текущую минуту (на границе окон возможен короткий
двойной темп — ретраи с бэкоффом в Grader это переживают). Слот берётся
один на стадию (recognize / grade): внутренние ретраи Grader и так
разнесены паузами 20–80с.
"""

import os
import time

from bot.queue import get_redis

GEMINI_RPM = int(os.environ.get('GEMINI_RPM', '15'))


def acquire_gemini_slot(conn=None, rpm: int = None, *, wait: float = 2.0,
                        timeout: float = 900.0, clock=time.time,
                        sleep=time.sleep):
    """Блокирует, пока не достанется слот в текущем минутном окне."""
    conn = conn if conn is not None else get_redis()
    rpm = rpm or GEMINI_RPM
    deadline = clock() + timeout
    while True:
        key = f'gemini_rpm:{int(clock() // 60)}'
        n = conn.incr(key)
        if n == 1:
            conn.expire(key, 120)
        if n <= rpm:
            return
        conn.decr(key)          # слот не достался — вернуть
        if clock() >= deadline:
            raise TimeoutError('не дождался слота запроса к Gemini')
        sleep(wait)

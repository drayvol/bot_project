"""SQLite-хранилище заявок. Общее для бота и воркера (volume + WAL).

Заявка (submission) — одно присланное решение: фото, OCR (исходный и
исправленный пользователем — их diff = бесплатная разметка), результат оценки.
"""

import json
import sqlite3
import time
import uuid
from contextlib import closing

from bot.config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    id           TEXT PRIMARY KEY,
    chat_id      INTEGER NOT NULL,
    user_id      INTEGER,
    photo_path   TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'new',
    ocr_original TEXT,
    ocr          TEXT,
    result       TEXT,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
"""

_JSON_FIELDS = ('ocr_original', 'ocr', 'result')


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def init_db():
    with closing(_connect()) as conn, conn:
        conn.executescript(_SCHEMA)
        try:
            conn.execute('ALTER TABLE submissions ADD COLUMN rating INTEGER')
        except sqlite3.OperationalError:
            pass  # колонка уже есть


def create_submission(chat_id: int, user_id: int, photo_path: str) -> str:
    sub_id = uuid.uuid4().hex[:12]
    now = time.time()
    with closing(_connect()) as conn, conn:
        conn.execute(
            'INSERT INTO submissions (id, chat_id, user_id, photo_path, status, created_at, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (sub_id, chat_id, user_id, photo_path, 'new', now, now))
    return sub_id


def get_submission(sub_id: str) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute('SELECT * FROM submissions WHERE id = ?', (sub_id,)).fetchone()
    if row is None:
        return None
    sub = dict(row)
    for f in _JSON_FIELDS:
        sub[f] = json.loads(sub[f]) if sub[f] else None
    return sub


def update_submission(sub_id: str, *, status: str = None, ocr: dict = None,
                      ocr_original: dict = None, result: dict = None,
                      rating: int = None):
    sets, vals = ['updated_at = ?'], [time.time()]
    if status is not None:
        sets.append('status = ?')
        vals.append(status)
    if rating is not None:
        sets.append('rating = ?')
        vals.append(rating)
    for name, val in (('ocr', ocr), ('ocr_original', ocr_original), ('result', result)):
        if val is not None:
            sets.append(f'{name} = ?')
            vals.append(json.dumps(val, ensure_ascii=False))
    vals.append(sub_id)
    with closing(_connect()) as conn, conn:
        conn.execute(f'UPDATE submissions SET {", ".join(sets)} WHERE id = ?', vals)

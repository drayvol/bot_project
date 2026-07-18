"""REST-интерфейс сервиса проверки решений задания №13.

Тонкий клиент над той же системой, что и Telegram-бот: пишет заявку
в SQLite и ставит задачи в очередь RQ; воркер не различает, откуда
пришла заявка. У REST-заявок chat_id = 0 — воркер не шлёт в Telegram,
клиент опрашивает GET /submissions/{id} до статуса awaiting_confirm / done.

Swagger: http://localhost:8000/docs
"""

import uuid

from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel

from bot import db
from bot.config import PHOTOS_DIR, ensure_dirs
from bot.queue import enqueue

app = FastAPI(
    title='EGE Task 13 Grader',
    description='Проверка фото рукописного решения задания №13 ЕГЭ (балл за пункт а).',
    version='1.0.0',
)

CONFIRMABLE = {'awaiting_confirm', 'editing', 'done'}


@app.on_event('startup')
def startup():
    ensure_dirs()
    db.init_db()


def _get_or_404(sub_id: str) -> dict:
    sub = db.get_submission(sub_id)
    if sub is None:
        raise HTTPException(404, 'заявка не найдена')
    return sub


def _public(sub: dict) -> dict:
    return {k: sub[k] for k in ('id', 'status', 'ocr_original', 'ocr',
                                'result', 'rating', 'created_at', 'updated_at')}


@app.post('/submissions', status_code=201)
async def create_submission(photo: UploadFile):
    """Принять фото решения; распознавание ставится в очередь."""
    if photo.content_type not in ('image/jpeg', 'image/png'):
        raise HTTPException(415, 'ожидается фото jpeg или png')
    path = f'{PHOTOS_DIR}/{uuid.uuid4().hex[:12]}_api.jpg'
    with open(path, 'wb') as f:
        f.write(await photo.read())

    sub_id = db.create_submission(0, 0, path)   # chat_id=0 → без Telegram
    position = enqueue('task_recognize', sub_id)
    return {'id': sub_id, 'status': 'new', 'queue_position': position}


@app.get('/submissions/{sub_id}')
def get_submission(sub_id: str):
    """Статус, распознанное решение и вердикт (для polling)."""
    return _public(_get_or_404(sub_id))


class OCRPatch(BaseModel):
    equation: str | None = None
    steps: list[str] | None = None
    answer: str | None = None


@app.patch('/submissions/{sub_id}/ocr')
def patch_ocr(sub_id: str, patch: OCRPatch):
    """Исправить распознанный OCR (аналог правок в боте)."""
    sub = _get_or_404(sub_id)
    if sub['ocr'] is None:
        raise HTTPException(409, 'распознавание ещё не готово')

    ocr = dict(sub['ocr'])
    if patch.equation is not None:
        ocr['equation'] = patch.equation
    if patch.answer is not None:
        ocr['answer'] = patch.answer
    if patch.steps is not None:
        ocr['steps'] = [{'type': '', 'latex': s, 'comment': 'правка пользователя'}
                        for s in patch.steps]
    db.update_submission(sub_id, ocr=ocr, status='editing')
    return _public(db.get_submission(sub_id))


@app.post('/submissions/{sub_id}/confirm')
def confirm(sub_id: str):
    """Подтвердить OCR и запустить оценку."""
    sub = _get_or_404(sub_id)
    if sub['ocr'] is None:
        raise HTTPException(409, 'распознавание ещё не готово')
    if sub['status'] not in CONFIRMABLE:
        raise HTTPException(409, f'нельзя подтвердить в статусе {sub["status"]}')

    db.update_submission(sub_id, status='grading')
    position = enqueue('task_grade', sub_id)
    return {'id': sub_id, 'status': 'grading', 'queue_position': position}


class Rating(BaseModel):
    rating: int  # 1 — 👍, 0 — 👎


@app.post('/submissions/{sub_id}/rating')
def rate(sub_id: str, body: Rating):
    """Оценить работу сервиса по заявке."""
    if body.rating not in (0, 1):
        raise HTTPException(422, 'rating должен быть 0 или 1')
    _get_or_404(sub_id)
    db.update_submission(sub_id, rating=body.rating)
    return {'id': sub_id, 'rating': body.rating}


@app.get('/health')
def health():
    return {'status': 'ok'}

"""Хендлеры: приём фото (в т.ч. альбомом), подтверждение и правка OCR."""

import asyncio
import io
import uuid

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BufferedInputFile, CallbackQuery,
                           InlineKeyboardMarkup, Message)
from PIL import Image

from bot import db
from bot.config import PHOTOS_DIR
from bot.keyboards import kb_confirm_ocr, kb_verdict
from bot.latex_render import ocr_as_text, render_ocr_png
from bot.ocr_edit import apply_edits
from bot.queue import enqueue

router = Router()

START_TEXT = (
    'Привет! Я проверяю задание №13 ЕГЭ (профиль): пришли фото рукописного '
    'решения уравнения — поставлю балл за пункт а) и объясню.\n\n'
    'Как это работает:\n'
    '1. Пришли фото (несколько страниц — одним альбомом).\n'
    '2. Я распознаю решение и покажу, что прочитал, — проверь и поправь, '
    'если я где-то ошибся в разборе почерка.\n'
    '3. После подтверждения оценю решение и покажу похожие задачи для тренировки.'
)

EDIT_HELP = (
    'Пришли правки, по одной на строку:\n'
    '«У: …» — заменить уравнение\n'
    '«3: …» — заменить шаг 3\n'
    '«3: -» — удалить шаг 3\n'
    '«+: …» — добавить шаг в конец\n'
    '«О: …» — заменить ответ\n\n'
    'Когда всё станет верно — жми «✅ Всё верно» под картинкой. /cancel — выйти.'
)


class EditOCR(StatesGroup):
    editing = State()


# ── команды ──

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(START_TEXT)


@router.message(Command('cancel'))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer('Ок, вышел из режима правки. Жду фото решения.')


# ── приём фото (одиночные и альбомы) ──

_albums: dict[str, dict] = {}   # media_group_id -> {'messages': [...], 'task': Task}
_ALBUM_SETTLE_S = 2.0


@router.message(F.photo)
async def on_photo(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    gid = message.media_group_id
    if gid is None:
        await _process_photos(bot, [message])
        return

    album = _albums.setdefault(gid, {'messages': [], 'task': None})
    album['messages'].append(message)
    if album['task']:
        album['task'].cancel()
    album['task'] = asyncio.create_task(_finalize_album(bot, gid))


async def _finalize_album(bot: Bot, gid: str):
    try:
        await asyncio.sleep(_ALBUM_SETTLE_S)
    except asyncio.CancelledError:
        return
    album = _albums.pop(gid, None)
    if album:
        await _process_photos(bot, album['messages'])


async def _process_photos(bot: Bot, messages: list[Message]):
    """Скачивает фото, склеивает страницы вертикально, ставит в очередь OCR."""
    first = messages[0]
    token = uuid.uuid4().hex[:12]
    parts = []
    for i, msg in enumerate(messages):
        path = f'{PHOTOS_DIR}/{token}_{i}.jpg'
        await bot.download(msg.photo[-1], destination=path)
        parts.append(path)

    photo_path = parts[0]
    if len(parts) > 1:
        photo_path = f'{PHOTOS_DIR}/{token}.jpg'
        await asyncio.to_thread(_stitch_vertical, parts, photo_path)

    sub_id = db.create_submission(first.chat.id, first.from_user.id, photo_path)
    position = enqueue('task_recognize', sub_id)
    pages = f' ({len(parts)} стр.)' if len(parts) > 1 else ''
    await first.answer(
        f'Принял фото{pages}. Распознаю решение — обычно это до минуты, '
        f'но иногда до 3–5 минут, если нейросеть капризничает.\n'
        f'Позиция в очереди: {position}')


def _stitch_vertical(paths: list[str], out_path: str):
    images = [Image.open(p).convert('RGB') for p in paths]
    width = max(im.width for im in images)
    canvas = Image.new('RGB', (width, sum(im.height for im in images)), 'white')
    y = 0
    for im in images:
        canvas.paste(im, ((width - im.width) // 2, y))
        y += im.height
    canvas.save(out_path, quality=92)


# ── подтверждение OCR / оценка ──

@router.callback_query(F.data.startswith('confirm:'))
async def on_confirm(callback: CallbackQuery, state: FSMContext):
    sub_id = callback.data.split(':', 1)[1]
    sub = db.get_submission(sub_id)
    if sub is None or sub['ocr'] is None:
        await callback.answer('Не нашёл эту заявку — пришли фото заново.', show_alert=True)
        return
    if sub['status'] == 'grading':
        await callback.answer('Уже оцениваю, немного терпения.')
        return

    await state.clear()
    db.update_submission(sub_id, status='grading')
    position = enqueue('task_grade', sub_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f'⏳ Оцениваю решение. Позиция в очереди: {position}')
    await callback.answer()


# ── правка OCR ──

@router.callback_query(F.data.startswith('edit:'))
async def on_edit(callback: CallbackQuery, state: FSMContext):
    sub_id = callback.data.split(':', 1)[1]
    sub = db.get_submission(sub_id)
    if sub is None or sub['ocr'] is None:
        await callback.answer('Не нашёл эту заявку — пришли фото заново.', show_alert=True)
        return

    await state.set_state(EditOCR.editing)
    await state.update_data(sub_id=sub_id)
    db.update_submission(sub_id, status='editing')
    await callback.message.answer(
        'Вот что я распознал:\n\n' + ocr_as_text(sub['ocr']) + '\n\n' + EDIT_HELP)
    await callback.answer()


@router.message(EditOCR.editing, F.text)
async def on_edit_text(message: Message, state: FSMContext):
    data = await state.get_data()
    sub = db.get_submission(data.get('sub_id', ''))
    if sub is None:
        await state.clear()
        await message.answer('Заявка потерялась — пришли фото заново.')
        return

    new_ocr, applied, rejected = apply_edits(sub['ocr'], message.text)
    if not applied:
        await message.answer('Не понял ни одной правки.\n\n' + EDIT_HELP)
        return

    db.update_submission(sub['id'], ocr=new_ocr)
    caption = 'Обновил: ' + ', '.join(applied) + '.'
    if rejected:
        caption += '\nНе понял: ' + '; '.join(rejected[:5])
    caption += '\nВсё верно теперь?'

    png = await asyncio.to_thread(render_ocr_png, new_ocr)
    await message.answer_photo(
        BufferedInputFile(png, filename='ocr.png'),
        caption=caption[:1024],
        reply_markup=InlineKeyboardMarkup.model_validate(kb_confirm_ocr(sub['id'])))


# ── похожие задачи ──

@router.callback_query(F.data.startswith('sim:'))
async def on_similar(callback: CallbackQuery):
    sub_id = callback.data.split(':', 1)[1]
    sub = db.get_submission(sub_id)
    if sub is None or sub['ocr'] is None:
        await callback.answer('Не нашёл эту заявку.', show_alert=True)
        return
    enqueue('task_similar', sub_id)
    await callback.answer('Ищу похожие задачи…')


# ── оценка работы бота ──

@router.callback_query(F.data.startswith('rate:'))
async def on_rate(callback: CallbackQuery):
    _, sub_id, val = callback.data.split(':')
    if db.get_submission(sub_id) is None:
        await callback.answer('Не нашёл эту заявку.', show_alert=True)
        return
    db.update_submission(sub_id, rating=int(val))
    try:
        await callback.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup.model_validate(
                kb_verdict(sub_id, rated=int(val))))
    except Exception:
        pass
    await callback.answer('Спасибо за оценку!')


@router.callback_query(F.data == 'noop')
async def on_noop(callback: CallbackQuery):
    await callback.answer()


# ── всё остальное ──

@router.message(F.text)
async def on_other_text(message: Message):
    await message.answer('Пришли фото рукописного решения задания №13 — я его проверю.')

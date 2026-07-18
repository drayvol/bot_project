"""RQ-задачи: распознавание, оценка, похожие задачи.

Выполняются в единственном воркере — это же и глобальный лимитер под
15 запросов/мин Gemini. Qdrant embedded открывается только здесь.
"""

import logging

from bot import db
from bot.config import SIMILAR_TOP_K
from bot.keyboards import kb_confirm_ocr, kb_verdict
from bot.latex_render import render_mixed_png, render_ocr_png
from bot.ratelimit import acquire_gemini_slot
from bot.validation import reject_reason
from worker.telegram import send_message, send_photo

logger = logging.getLogger(__name__)

_grader = None


def _get_grader():
    global _grader
    if _grader is None:
        from grade_solution import Grader
        _grader = Grader()
    return _grader


def _load(sub_id: str) -> dict:
    sub = db.get_submission(sub_id)
    if sub is None:
        raise RuntimeError(f'submission {sub_id} не найдена')
    return sub


def _fail(sub: dict, stage: str, e: Exception):
    logger.exception('%s failed for %s', stage, sub['id'])
    db.update_submission(sub['id'], status='error')
    if sub['chat_id']:   # REST-заявки (chat_id=0) узнают статус через GET
        send_message(sub['chat_id'],
                     '😔 Что-то пошло не так при обработке (внешний сервис не ответил). '
                     'Попробуй прислать фото ещё раз чуть позже.')
    raise e


# ── распознавание ──

def task_recognize(sub_id: str):
    sub = _load(sub_id)
    try:
        acquire_gemini_slot()
        ocr = _get_grader().recognize(sub['photo_path'])
    except Exception as e:
        _fail(sub, 'recognize', e)

    reason = reject_reason(ocr)
    if reason is not None:
        db.update_submission(sub_id, ocr=ocr, ocr_original=ocr, status='rejected')
        if sub['chat_id']:
            send_message(sub['chat_id'], reason)
        return

    db.update_submission(sub_id, ocr=ocr, ocr_original=ocr, status='awaiting_confirm')
    if sub['chat_id']:
        png = render_ocr_png(ocr)
        send_photo(
            sub['chat_id'], png,
            caption='Вот что я прочитал в решении. Сверь с оригиналом: если я '
                    'где-то ошибся в почерке — жми «Исправить», это важно для оценки.',
            reply_markup=kb_confirm_ocr(sub_id))


# ── оценка ──

def task_grade(sub_id: str):
    sub = _load(sub_id)
    try:
        acquire_gemini_slot()
        result = _get_grader().grade(sub['photo_path'], sub['ocr'])
    except Exception as e:
        _fail(sub, 'grade', e)

    db.update_submission(sub_id, result=result, status='done')
    if sub['chat_id']:
        send_message(sub['chat_id'], _format_verdict(result),
                     reply_markup=kb_verdict(sub_id))
    _store_equation(sub, result)


def _store_equation(sub: dict, result: dict):
    """Пополняет базу присланным уравнением (не критично — только логируем)."""
    try:
        from user_equations import add_user_equation
        status = add_user_equation(
            (sub['ocr'] or {}).get('equation', ''), sub['id'],
            {'answer': str((sub['ocr'] or {}).get('answer', '')),
             'score': result.get('score'),
             'suspicious_ocr': bool(result.get('suspicious_ocr'))})
        logger.info('user equation for %s: %s', sub['id'], status)
    except Exception:
        logger.exception('не удалось сохранить уравнение %s в базу', sub['id'])


def _format_verdict(result: dict) -> str:
    score = result.get('score')
    if score == 1:
        head = '✅ Балл за пункт а): 1 из 1'
    elif score == 0:
        head = '❌ Балл за пункт а): 0 из 1'
    else:
        head = '🤔 Не смог уверенно оценить это решение'

    src = ('формальная проверка выкладок'
           if result.get('verdict_source') == 'checker'
           else 'проверка с разбором шагов')
    parts = [head, f'({src})']

    if result.get('llm_comment'):
        comment = result['llm_comment'].strip()
        if len(comment) > 1500:
            comment = comment[:1500] + '…'
        parts.append('\n' + comment)

    if result.get('suspicious_ocr'):
        parts.append(
            '\n⚠️ Есть подозрение, что я неточно распознал запись (например, '
            'перепутал похожие символы). Если оценка кажется несправедливой — '
            'нажми «Исправить распознавание и пересчитать».')

    parts.append('\nОцени, пожалуйста, мою проверку кнопками 👍/👎 внизу — '
                 'это помогает мне становиться точнее.')
    return '\n'.join(parts)


# ── похожие задачи ──

def task_similar(sub_id: str):
    sub = _load(sub_id)
    equation = (sub['ocr'] or {}).get('equation', '')
    if not equation:
        send_message(sub['chat_id'], 'Не нашёл уравнение в этой заявке.')
        return

    try:
        hits = _get_grader().similar_tasks(equation, top_k=SIMILAR_TOP_K)
    except Exception as e:
        _fail(sub, 'similar', e)

    if not hits:
        send_message(sub['chat_id'], 'Похожих задач не нашлось.')
        return

    send_message(sub['chat_id'], '📚 Похожие задачи для тренировки:')
    for i, hit in enumerate(hits, 1):
        png = render_mixed_png(_format_similar(i, hit))
        send_photo(sub['chat_id'], png, caption=f'Задача {i}')


def _format_similar(n: int, hit: dict) -> str:
    condition = hit.get('condition') or f'Решите уравнение: ${hit.get("equation", "")}$'
    text = f'Задача {n}. {condition}'
    solution = (hit.get('solution') or '').strip()
    if solution:
        if len(solution) > 3000:
            solution = solution[:3000] + '…'
        text += f'\n{solution}'
    answer = (hit.get('answer') or '').strip()
    # в базе решение обычно уже кончается ответом — не дублируем
    if answer and answer not in text:
        text += f'\n{answer}'
    return text

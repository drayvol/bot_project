"""Проверка результата OCR: похоже ли фото на решение уравнения.

Двойная защита: модель может явно вернуть not_math=true (правило в
OCR_SYSTEM_PROMPT), а если она всё же что-то «извлекла» из кота на фото —
ловим по структуре результата.
"""

REJECT_NOT_MATH = (
    'Хм, на фото не видно решения уравнения{reason}. '
    'Пришли фото рукописного решения задания №13 — уравнение, шаги и ответ.')

REJECT_NO_EQUATION = (
    'Не смог найти на фото уравнение. Проверь, что снято рукописное '
    'решение задания №13 целиком и условие читается, и пришли фото ещё раз.')

REJECT_NOT_EQUATION = (
    'То, что я прочитал, не похоже на уравнение — не вижу знака равенства. '
    'Я умею проверять только задание №13 (уравнения). Если это оно, '
    'пришли фото почётче.')

REJECT_NO_STEPS = (
    'Вижу уравнение, но не вижу шагов решения — похоже, это только условие. '
    'Пришли фото с самим решением: преобразования, корни, ответ.')


def reject_reason(ocr: dict) -> str | None:
    """None — всё в порядке, иначе текст отказа для пользователя."""
    if ocr.get('not_math'):
        reason = str(ocr.get('reason', '') or '').strip()
        return REJECT_NOT_MATH.format(reason=f' (похоже, там: {reason})' if reason else '')

    equation = str(ocr.get('equation', '') or '').strip()
    if not equation:
        return REJECT_NO_EQUATION
    if '=' not in equation:
        return REJECT_NOT_EQUATION

    steps = ocr.get('steps') or []
    answer = str(ocr.get('answer', '') or '').strip()
    if not steps and not answer:
        return REJECT_NO_STEPS

    return None

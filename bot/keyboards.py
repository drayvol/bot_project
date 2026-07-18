"""Inline-клавиатуры как plain-dict (Bot API reply_markup).

Dict, а не aiogram-типы, потому что воркер шлёт их напрямую через HTTP;
бот заворачивает в InlineKeyboardMarkup.model_validate().
"""


def kb_confirm_ocr(sub_id: str) -> dict:
    return {'inline_keyboard': [
        [{'text': '✅ Всё верно, оценивай', 'callback_data': f'confirm:{sub_id}'}],
        [{'text': '✏️ Исправить распознавание', 'callback_data': f'edit:{sub_id}'}],
    ]}


def kb_verdict(sub_id: str, rated: int = None) -> dict:
    rows = [
        [{'text': '📚 Похожие задачи', 'callback_data': f'sim:{sub_id}'}],
        [{'text': '✏️ Исправить распознавание и пересчитать',
          'callback_data': f'edit:{sub_id}'}],
    ]
    if rated is None:
        rows.append([
            {'text': '👍', 'callback_data': f'rate:{sub_id}:1'},
            {'text': '👎', 'callback_data': f'rate:{sub_id}:0'},
        ])
    else:
        rows.append([{'text': '👍 Спасибо за оценку!' if rated else '👎 Спасибо за оценку!',
                      'callback_data': 'noop'}])
    return {'inline_keyboard': rows}

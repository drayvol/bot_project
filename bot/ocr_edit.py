"""Парсер правок OCR из текстового сообщения пользователя.

Формат (по строке на правку):
    У: 2\\sin^2 x - 1 = 0        — заменить уравнение
    3: \\sin x = \\frac{1}{2}    — заменить шаг 3
    3: -                          — удалить шаг 3
    +: x = \\pi k                 — добавить шаг в конец
    О: x = \\pi/6 + 2\\pi k       — заменить ответ
"""

import copy
import re

# шаг OCR — dict {'type','latex','comment'} (так его ждёт normalize_steps
# в grade()); правки меняют только latex, структуру сохраняем


def _set_step_latex(steps: list, idx: int, latex: str):
    if isinstance(steps[idx], dict):
        steps[idx] = {**steps[idx], 'latex': latex,
                      'comment': 'правка пользователя'}
    else:
        steps[idx] = {'type': '', 'latex': latex,
                      'comment': 'правка пользователя'}


_RX_EQUATION = re.compile(r'^\s*(?:у|u|ур|уравнение)\s*[:=]\s*(.*)$', re.I)
_RX_ANSWER = re.compile(r'^\s*(?:о|o|отв|ответ)\s*[:=]\s*(.*)$', re.I)
_RX_STEP = re.compile(r'^\s*(\d+)\s*[:.]\s*(.*)$')
_RX_APPEND = re.compile(r'^\s*\+\s*[:=]?\s*(.*)$')


def apply_edits(ocr: dict, text: str) -> tuple[dict, list[str], list[str]]:
    """Возвращает (новый ocr, применённые правки, непонятые строки)."""
    ocr = copy.deepcopy(ocr)
    steps = list(ocr.get('steps') or [])
    applied, rejected = [], []

    for line in text.splitlines():
        if not line.strip():
            continue
        if m := _RX_EQUATION.match(line):
            ocr['equation'] = m.group(1).strip()
            applied.append('уравнение')
        elif m := _RX_ANSWER.match(line):
            ocr['answer'] = m.group(1).strip()
            applied.append('ответ')
        elif m := _RX_APPEND.match(line):
            steps.append({'type': '', 'latex': m.group(1).strip(),
                          'comment': 'добавлено пользователем'})
            applied.append(f'добавлен шаг {len(steps)}')
        elif m := _RX_STEP.match(line):
            n, val = int(m.group(1)), m.group(2).strip()
            if 1 <= n <= len(steps):
                if val in ('-', '—'):
                    steps.pop(n - 1)
                    applied.append(f'удалён шаг {n}')
                else:
                    _set_step_latex(steps, n - 1, val)
                    applied.append(f'шаг {n}')
            else:
                rejected.append(line.strip())
        else:
            rejected.append(line.strip())

    ocr['steps'] = steps
    return ocr, applied, rejected

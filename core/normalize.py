"""Нормализация LaTeX перед формальным чекером.

OCR возвращает «человеческий» LaTeX (\\text, \\quad, стрелки следствия),
чекер ждёт голое уравнение — приводим одно к другому.
"""

import re


def normalize_latex(s: str) -> str:
    if not s:
        return s

    # \text{...} — убираем обёртку, оставляем содержимое
    s = re.sub(r'\\text\{([^}]*)\}', r'\1', s)

    # \quad, \qquad — пробелы
    s = re.sub(r'\\q?quad', ' ', s)

    # стрелки следствия для чекера эквивалентны «=»
    s = re.sub(r'\\implies|\\Rightarrow|\\Leftrightarrow|\\Longrightarrow', '=', s)

    # \mathbb{Z}, \in, \notin — декор, парсингу уравнения только мешает
    s = re.sub(r'\\mathbb\{[A-Z]\}', '', s)
    s = re.sub(r'\\(?:not)?in\b', '', s)

    s = re.sub(r'  +', ' ', s)
    return s.strip()


def normalize_steps(steps: list) -> list:
    """Шаги OCR ({'type','latex','comment'}) с нормализованным latex."""
    return [{
        'type':    step.get('type', ''),
        'latex':   normalize_latex(step.get('latex', '')),
        'comment': step.get('comment', ''),
    } for step in steps]

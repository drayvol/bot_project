"""Нормализация LaTeX и шагов перед чекером."""

from evaluate_sympy import normalize_latex, normalize_steps


def test_normalize_steps_dicts():
    steps = normalize_steps([
        {'type': 'замена', 'latex': r'\sin x = t', 'comment': 'c'},
        {'type': '', 'latex': '', 'comment': ''},
    ])
    assert steps[0]['type'] == 'замена'
    assert steps[0]['latex']  # нормализация не потеряла содержимое
    assert len(steps) == 2


def test_normalize_latex_text_wrapper():
    assert 'text' not in normalize_latex(r'\text{Ответ: } x = 1')


def test_normalize_latex_empty():
    assert normalize_latex('') == ''

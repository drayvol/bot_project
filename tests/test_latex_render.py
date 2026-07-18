"""Рендер LaTeX → PNG и перенос смешанного текста."""

from bot.latex_render import (_wrap_mixed, ocr_as_text, render_mixed_png,
                              render_ocr_png, step_latex)

PNG_MAGIC = b'\x89PNG'


def test_render_ocr_png_with_dict_steps():
    png = render_ocr_png({
        'equation': r'2\sin^2 x - 1 = 0',
        'steps': [{'type': 'т', 'latex': r'x = \frac{\pi}{4} + \pi k', 'comment': ''}],
        'answer': r'\frac{\pi}{4}',
    })
    assert png.startswith(PNG_MAGIC)


def test_render_survives_unrenderable_latex():
    # \begin{cases} mathtext не умеет — должен сработать monospace-фолбэк
    png = render_ocr_png({'equation': r'\begin{cases} x = 1 \\ x = 2 \end{cases}',
                          'steps': [], 'answer': ''})
    assert png.startswith(PNG_MAGIC)


def test_render_mixed_png():
    png = render_mixed_png(r'Решение. а) Пусть $t = 3^{x-1}$ тогда $3t^2 - 8t + 5 = 0$')
    assert png.startswith(PNG_MAGIC)


def test_wrap_mixed_keeps_math_chunks_whole():
    text = 'слово ' * 20 + r'$\frac{-\sqrt{3} + 3\sqrt{3}}{4} = \frac{\sqrt{3}}{2}$' + ' хвост' * 20
    for line in _wrap_mixed(text, width=40):
        assert line.count('$') % 2 == 0, f'разорванная формула: {line}'


def test_step_latex_and_ocr_as_text():
    assert step_latex({'latex': 'x=1', 'type': '', 'comment': ''}) == 'x=1'
    assert step_latex('x=2') == 'x=2'
    text = ocr_as_text({'equation': 'e', 'steps': [{'latex': 's1'}, 's2'], 'answer': 'a'})
    assert text.splitlines() == ['У: e', '1: s1', '2: s2', 'О: a']

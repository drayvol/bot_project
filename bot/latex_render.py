"""Рендер LaTeX в PNG для показа пользователю.

Matplotlib mathtext — без texlive. Что mathtext не переваривает
(\begin{cases} и т.п.) — рисуем исходной строкой в monospace, читаемо.

Два режима:
- render_ocr_png: распознанное решение (шаг OCR — dict {'type','latex','comment'});
- render_mixed_png: проза с $…$-вставками (условия/решения похожих задач).

Каждая строка рендерится отдельной картинкой, потом склейка по вертикали —
так длинные строки не наезжают друг на друга.
"""

import io
import re
import textwrap

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.mathtext import MathTextParser
from PIL import Image

_parser = MathTextParser('agg')


def step_latex(step) -> str:
    """LaTeX шага: шаг может быть dict из OCR или голой строкой."""
    if isinstance(step, dict):
        return str(step.get('latex', ''))
    return str(step)


# mathtext не знает \text и русских имён функций; пробелы внутри \text
# приходится экранировать, иначе mathtext их съедает
def _text_to_mathrm(m: re.Match) -> str:
    return r'\mathrm{' + m.group(1).replace(' ', r'\ ') + '}'


_REPLACEMENTS = [
    (re.compile(r'\\text\s*\{([^{}]*)\}'), _text_to_mathrm),
    (re.compile(r'\\(tg|ctg|arctg|arcctg)\b'), r'\\mathrm{\1}\\,'),
    (re.compile(r'\\degree\b'), r'^\\circ'),
]


def _prepare(latex: str) -> str:
    s = latex.strip()
    for rx, repl in _REPLACEMENTS:
        s = rx.sub(repl, s)
    return s


def _renderable(line: str) -> bool:
    try:
        _parser.parse(line, dpi=100)
        return True
    except Exception:
        return False


def _text_image(text: str, family: str = None, fontsize: int = 14) -> Image.Image:
    fig = plt.figure(figsize=(10, 1), dpi=150)
    fig.patch.set_facecolor('white')
    fig.text(0.01, 0.5, text, fontsize=fontsize, va='center', family=family)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.12,
                facecolor='white')
    plt.close(fig)
    return Image.open(buf).convert('RGB')


def _line_image(label: str, latex: str) -> Image.Image:
    """Строка «метка + формула» (mathtext, при ошибке — monospace с переносом)."""
    prepared = _prepare(latex)
    if prepared:
        mixed = f'{label}  ${prepared}$'
        if _renderable(mixed):
            return _text_image(mixed)
    text = f'{label}  {latex.strip() or "—"}'
    text = '\n'.join(textwrap.wrap(text, 90, subsequent_indent='    ')) or '—'
    return _text_image(text, family='monospace')


def _mixed_line_image(line: str) -> Image.Image:
    """Строка прозы с $…$-вставками."""
    prepared = _prepare(line)
    if '$' not in prepared or _renderable(prepared):
        return _text_image(prepared)
    return _text_image('\n'.join(textwrap.wrap(line, 90)), family='monospace')


def _stack(images: list[Image.Image]) -> bytes:
    pad, gap = 20, 10
    width = max(im.width for im in images) + 2 * pad
    height = sum(im.height for im in images) + gap * (len(images) - 1) + 2 * pad
    canvas = Image.new('RGB', (width, height), 'white')
    y = pad
    for im in images:
        canvas.paste(im, (pad, y))
        y += im.height + gap

    # лимиты Telegram на фото: w+h ≤ 10000, соотношение ≤ 20
    if width + height > 10000:
        scale = 10000 / (width + height)
        canvas = canvas.resize((int(width * scale), int(height * scale)))

    buf = io.BytesIO()
    canvas.save(buf, format='PNG')
    return buf.getvalue()


def render_ocr_png(ocr: dict) -> bytes:
    """PNG с уравнением, шагами и ответом."""
    images = [_line_image('Уравнение:', str(ocr.get('equation', '') or ''))]
    for i, step in enumerate(ocr.get('steps') or [], 1):
        images.append(_line_image(f'{i}.', step_latex(step)))
    images.append(_line_image('Ответ:', str(ocr.get('answer', '') or '')))
    return _stack(images)


_MATH_CHUNK = re.compile(r'\$[^$]*\$')


def _wrap_mixed(text: str, width: int = 85) -> list[str]:
    """Перенос строк, не разрывая $…$-вставки."""
    lines = []
    for paragraph in text.splitlines():
        if not paragraph.strip():
            continue
        # токены: $…$ целиком или слова
        tokens = re.findall(r'\$[^$]*\$|\S+', paragraph)
        cur = ''
        for tok in tokens:
            candidate = f'{cur} {tok}'.strip()
            if cur and len(candidate) > width:
                lines.append(cur)
                cur = tok
            else:
                cur = candidate
        if cur:
            lines.append(cur)
    return lines


def render_mixed_png(text: str) -> bytes:
    """PNG из прозы с $…$-вставками (условие/решение задачи)."""
    lines = _wrap_mixed(text) or ['—']
    return _stack([_mixed_line_image(line) for line in lines])


def ocr_as_text(ocr: dict) -> str:
    """Текстовый вид для режима правки: пронумерованные строки."""
    out = [f'У: {ocr.get("equation", "")}']
    for i, step in enumerate(ocr.get('steps') or [], 1):
        out.append(f'{i}: {step_latex(step)}')
    out.append(f'О: {ocr.get("answer", "")}')
    return '\n'.join(out)

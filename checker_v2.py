"""
checker_v2.py
Проверка решения ЕГЭ задания 13.
"""

import os
import re
import math
import numpy as np
from scipy.optimize import brentq

import sympy as sp
from sympy import symbols, sympify, solveset, S, sin, cos, tan, pi
from sympy.abc import x
t = symbols('t')

try:
    import wolframalpha as _wa
    _WA_CLIENT = _wa.Client(os.environ['WOLFRAM_API_KEY']) if os.environ.get('WOLFRAM_API_KEY') else None
except Exception:
    _WA_CLIENT = None

# Классификатор типа уравнения (mixed / ordinary) для маршрутизации в Wolfram:
# смешанные лог/экспоненциальные уравнения sympy часто не решает — для них
# включаем Wolfram; обычные тригонометрические решаем только sympy.
try:
    import joblib as _joblib
    _EQ_TYPE_CLF = _joblib.load(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     'models/equation_type_logreg.joblib'))
except Exception:
    _EQ_TYPE_CLF = None


def classify_equation_type(equation_latex: str) -> str:
    """'mixed' или 'ordinary'. Без классификатора считаем всё mixed (безопасно)."""
    if _EQ_TYPE_CLF is None or not isinstance(equation_latex, str):
        return 'mixed'
    try:
        return _EQ_TYPE_CLF.predict([equation_latex])[0]
    except Exception:
        return 'mixed'

# ──────────────────────────────────────────────
# LaTeX → sympy строка
# ──────────────────────────────────────────────

def latex_to_str(latex: str) -> str:
    s = latex.strip()

    # 0. Десятичная запятая → точка (0,5 → 0.5), иначе sympify даёт tuple
    s = re.sub(r'(\d),(\d)', r'\1.\2', s)

    # 0.1. Голый tg (без слеша, от OCR) → \tan, чтобы работали остальные правила
    s = re.sub(r'(?<![a-zA-Z\\])tg(?![a-zA-Z])', r'\\tan', s)

    # 0.2. Смешанное число: 1\frac{1}{2} → (1 + 1/2). В записи ЕГЭ цифра
    # вплотную к дроби — это полторы, а не умножение
    s = re.sub(r'(\d)\s*\\frac\{(\d+)\}\{(\d+)\}', r'(\1 + (\2)/(\3))', s)

    # 0.3. Степень логарифма: \log_{2}^{2}(arg) → (\log_{2}(arg))^{2}
    for _ in range(2):
        s = re.sub(r'\\log_\{?(\d+)\}?\^\{?(\d+)\}?\s*\(([^()]*)\)',
                   r'(\\log_{\1}(\3))^{\2}', s)

    # 1. \left( \right) → скобки
    s = re.sub(r'\\left\s*\(', '(', s)
    s = re.sub(r'\\right\s*\)', ')', s)
    s = re.sub(r'\\left\s*\[', '(', s)
    s = re.sub(r'\\right\s*\]', ')', s)
    s = re.sub(r'\\left\s*\\?\{', '(', s)
    s = re.sub(r'\\right\s*\\?\}', ')', s)

    # 2.5. \log_{9}(expr) → log(expr, 9)  — ДО замены { → (
    # Ловим: \log_{base}( или \log_{base}\left(
    def replace_log(m):
        base = m.group(1)
        return f'LOG_BASE_{base}_('
    s = re.sub(r'\\log_\{(\d+)\}\s*\\?left\s*\(', replace_log, s)
    s = re.sub(r'\\log_\{(\d+)\}\s*\(', replace_log, s)
    s = re.sub(r'\\log_(\d+)\s*\(', lambda m: f'LOG_BASE_{m.group(1)}_(', s)
    s = re.sub(r'\\ln\s*\(', 'LOG_BASE_e_(', s)
    # \log_{9}9^{x} — логарифм без скобок, аргумент до пробела/конца
    s = re.sub(r'\\log_\{(\d+)\}\s*(\d+)', lambda m: f'log({m.group(2)}, {m.group(1)})', s)
    s = re.sub(r'\\log_(\d+)\s*(\d+)', lambda m: f'log({m.group(2)}, {m.group(1)})', s)

    # 2.6. \cos^{2}x (степень после функции, аргумент без скобок) → TRIG метка
    s = re.sub(r'\\(sin|cos|tan)\^\{(\d+)\}\s*(?!\()', r'TRIG_\1_\2_NOPAREN_', s)
    s = re.sub(r'\\(sin|cos|tan)\^(\d+)\s*(?!\()', r'TRIG_\1_\2_NOPAREN_', s)


    #    чтобы не перепутать с обычным ^ после аргумента
    s = re.sub(r'\\(sin|cos|tan)\^\{(\d+)\}\s*\(', r'TRIG_\1_\2_(', s)
    s = re.sub(r'\\(sin|cos|tan)\^(\d+)\s*\(', r'TRIG_\1_\2_(', s)

    # 4. Обычные trig/константы
    s = re.sub(r'\\sin', 'sin', s)
    s = re.sub(r'\\cos', 'cos', s)
    s = re.sub(r'\\tan', 'tan', s)
    s = re.sub(r'\\tg',  'tan', s)
    s = re.sub(r'\\pi',  'pi',  s)
    s = re.sub(r'\\cdot', '*',  s)

    # 5. \sqrt{a} → sqrt(a) — ДО \frac, чтобы \frac{\sqrt{2}}{2} правильно парсился
    s = re.sub(r'\\sqrt\{([^{}]+)\}', r'sqrt(\1)', s)
    s = re.sub(r'\\sqrt', 'sqrt', s)

    # 6. \frac{a}{b} → ((a)/(b)) — несколько проходов для вложенных;
    # паттерн допускает один уровень вложенных {} внутри числителя/знаменателя
    _frac_part = r'((?:[^{}]|\{[^{}]*\})+)'
    for _ in range(4):
        s = re.sub(r'\\frac\{' + _frac_part + r'\}\{' + _frac_part + r'\}',
                   r'((\1)/(\2))', s)

    # 7. ^ { } → ** ( )
    s = re.sub(r'\^', '**', s)
    s = re.sub(r'\{', '(', s)
    s = re.sub(r'\}', ')', s)

    # 7.9. NOPAREN перед скобкой (возникает после конвертации \frac):
    # TRIG_cos_2_NOPAREN_((x)/(2)) → TRIG_cos_2_((x)/(2)) — обработает walker
    s = re.sub(r'TRIG_(sin|cos|tan)_(\d+)_NOPAREN_\s*\(', r'TRIG_\1_\2_(', s)

    # 8. Разворачиваем метки TRIG_sin_2_( → sin(arg)**2
    pattern = re.compile(r'TRIG_(sin|cos|tan)_(\d+)_\(')
    result = []
    i = 0
    while i < len(s):
        m = pattern.match(s, i)
        if m:
            fn, pw = m.group(1), m.group(2)
            depth = 1
            j = m.end()
            while j < len(s) and depth > 0:
                if s[j] == '(':   depth += 1
                elif s[j] == ')': depth -= 1
                j += 1
            arg = s[m.end():j-1]
            result.append(f'{fn}({arg})**{pw}')
            i = j
        else:
            result.append(s[i])
            i += 1
    s = ''.join(result)

    # 8.2 Разворачиваем LOG_BASE_9_( → log(arg, 9)
    log_pattern = re.compile(r'LOG_BASE_(\w+)_\(')
    result2 = []
    i = 0
    while i < len(s):
        m = log_pattern.match(s, i)
        if m:
            base = m.group(1)
            depth = 1
            j = m.end()
            while j < len(s) and depth > 0:
                if s[j] == '(':   depth += 1
                elif s[j] == ')': depth -= 1
                j += 1
            arg = s[m.end():j-1]
            if base == 'e':
                result2.append(f'log({arg})')
            else:
                result2.append(f'log({arg}, {base})')
            i = j
        else:
            result2.append(s[i])
            i += 1
    s = ''.join(result2)

    # 8.3 Разворачиваем TRIG_cos_2_NOPAREN_ x → cos(x)**2
    s = re.sub(r'TRIG_(sin|cos|tan)_(\d+)_NOPAREN_\s*([a-z])', r'\1(\3)**\2', s)
    s = re.sub(r'TRIG_(sin|cos|tan)_(\d+)_NOPAREN_\s*\(', r'\1(**\2*(', s)  # fallback


    # Сначала добавляем * между цифрой и буквой: 2x → 2*x (нужно до cos 2*x)
    s = re.sub(r'(\d)([a-zA-Z])', r'\1*\2', s)
    # cos 2*x → cos(2*x)
    s = re.sub(r'(sin|cos|tan)\s+(\d+\*[a-z])', r'\1(\2)', s)
    # cos ( → cos(
    s = re.sub(r'(sin|cos|tan)\s+\(', r'\1(', s)

    # 9. Implicit multiplication (порядок важен):
    # цифра перед буквой: 2t → 2*t, 6x → 6*x
    s = re.sub(r'(\d)([a-zA-Z])', r'\1*\2', s)
    # цифра + пробел + буква/скобка: "2 sin(x)" → "2*sin(x)", "4 (" → "4*("
    s = re.sub(r'(\d)\s+([a-zA-Z(])', r'\1*\2', s)
    # цифра вплотную к скобке: "2(log..." → "2*(log..."
    s = re.sub(r'(\d)\(', r'\1*(', s)
    # переменная, склеенная с функцией: "xcos(x)" → "x*cos(x)" (из "2x\cos x")
    s = re.sub(r'(?<![a-zA-Z])([xt])(sin|cos|tan|sqrt|log|pi)', r'\1*\2', s)
    # trig без скобок перед переменной: sin x → sin(x), cos t → cos(t)
    s = re.sub(r'(sin|cos|tan)\s+([a-z])', r'\1(\2)', s)
    # trig**n x → trig(x)**n (если осталось)
    s = re.sub(r'(sin|cos|tan)\*\*(\d+)\s+([a-z])', r'\1(\3)**\2', s)
    # закрытая скобка перед функцией/переменной: )sin → )*sin
    s = re.sub(r'\)\s*(sin|cos|tan|sqrt|log|pi|[a-zA-Z])', r')*\1', s)
    # закрытая скобка перед открытой: ) ( → )*(
    # применяем ДВАЖДЫ — второй раз подхватывает случаи после предыдущих замен
    s = re.sub(r'\)\s*\(', ')*(', s)
    s = re.sub(r'\)\s*\(', ')*(', s)

    return s


def parse_expr(latex: str):
    try:
        s = latex_to_str(latex)
        return sympify(s, locals={
            'sin': sin, 'cos': cos, 'tan': tan,
            'pi': pi, 'sqrt': sp.sqrt, 'x': x, 't': t,
            'log': sp.log,
        })
    except Exception:
        return None


def parse_equation(latex: str):
    """lhs = rhs → lhs - rhs"""
    if '=' not in latex:
        return None
    parts = latex.split('=', 1)
    lhs = parse_expr(parts[0])
    rhs = parse_expr(parts[1])
    if lhs is None or rhs is None:
        return None
    return lhs - rhs


# ──────────────────────────────────────────────
# Решатели
# ──────────────────────────────────────────────

def _solve_symbolic(equation_latex: str):
    expr = parse_equation(equation_latex)
    if expr is None:
        return None

    import signal

    def _timeout_handler(signum, frame):
        raise TimeoutError()

    try:
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(5)  # 5 секунд максимум
        raw = sp.solve(expr, x)
        signal.alarm(0)
        if not raw:
            return None

        # Разворачиваем по нескольким периодам: добавляем k*pi и k*2pi
        base = [round(float(s), 8) for s in raw if not s.free_symbols]
        if not base:
            return None

        lo, hi = -2 * math.pi, 4 * math.pi
        roots = set()
        for r in base:
            # Добавляем сдвиги кратные pi (период π и 2π покрывают оба случая)
            for k in range(-4, 5):
                for period in [math.pi, 2 * math.pi]:
                    val = round(r + k * period, 8)
                    if lo - 1e-9 <= val <= hi + 1e-9:
                        # Проверяем что это действительно корень
                        try:
                            check = float(expr.subs(x, val))
                            if abs(check) < 1e-6:
                                roots.add(val)
                        except Exception:
                            pass

        return sorted(roots) if roots else None
    except (Exception, TimeoutError):
        signal.alarm(0)
        return None


def _solve_numeric(equation_latex: str, lo=-2*math.pi, hi=4*math.pi, n_pts=2000):
    expr = parse_equation(equation_latex)
    if expr is None:
        return None

    def f(v):
        try:
            return float(expr.subs(x, v))
        except Exception:
            return float('nan')

    xs = np.linspace(lo, hi, n_pts)
    ys = np.array([f(v) for v in xs])
    roots = []
    for i in range(len(xs) - 1):
        y0, y1 = ys[i], ys[i + 1]
        if math.isnan(y0) or math.isnan(y1):
            continue
        if y0 * y1 < 0:
            try:
                r = brentq(f, xs[i], xs[i + 1], xtol=1e-9)
                r = round(r, 8)
                if not any(abs(r - e) < 1e-6 for e in roots):
                    roots.append(r)
            except Exception:
                pass
    return sorted(roots) if roots else None


def _solve_wolfram(equation_latex: str,
                   lo=-2 * math.pi, hi=4 * math.pi) -> list | None:
    """
    Решает уравнение через Wolfram Alpha REST API.
    Возвращает список числовых корней в диапазоне [lo, hi] или None.
    """
    import requests as _requests

    app_id = os.environ.get('WOLFRAM_API_KEY', '')
    if not app_id or not isinstance(equation_latex, str):
        return None

    # LaTeX → plain math для Wolfram
    eq = equation_latex
    for _ in range(4):
        eq = re.sub(r'\\frac\{([^{}]+)\}\{([^{}]+)\}', r'(\1)/(\2)', eq)
    eq = re.sub(r'\\left|\\right', '', eq)
    # \log_{4}^{2}(arg) → (log_4(arg))^2  — степень логарифма
    eq = re.sub(r'\\log_\{?(\d+)\}?\^\{?(\d+)\}?\s*\(([^()]*)\)', r'(log_\1(\3))^\2', eq)
    eq = re.sub(r'\\log_\{?(\d+)\}?', r'log_\1', eq)
    eq = re.sub(r'\\ln', 'ln', eq)
    eq = re.sub(r'\\cdot', '*', eq)
    eq = re.sub(r'\\sqrt\{([^{}]+)\}', r'sqrt(\1)', eq)
    eq = re.sub(r'\\sqrt', 'sqrt', eq)
    eq = re.sub(r'\\?tg', 'tan', eq)   # \tg и голый tg от OCR
    eq = re.sub(r'\\(sin|cos|tan)', r'\1', eq)
    eq = re.sub(r'\\pi', 'pi', eq)
    eq = re.sub(r'\\pm', '±', eq)
    eq = re.sub(r'[{}]', '', eq)
    # ^ и неявное умножение НЕ конвертируем: Wolfram сам понимает "sin^2 x", "2x"

    try:
        resp = _requests.get(
            'https://api.wolframalpha.com/v2/query',
            params={'input': f'solve {eq} for real x', 'appid': app_id, 'output': 'json'},
            timeout=20,
        )
        pods = resp.json()['queryresult'].get('pods', [])
    except Exception:
        return None

    # Собираем текст из подов Solution / Result
    texts = []
    for pod in pods:
        if 'solution' in pod['title'].lower() or 'result' in pod['title'].lower():
            for sub in pod.get('subpods', []):
                t = sub.get('plaintext', '')
                if t:
                    texts.append(t)

    if not texts:
        return None

    roots = []
    n_sym = symbols('n', integer=True)
    locals_ = {'pi': pi, 'sqrt': sp.sqrt, 'n': n_sym}

    for text in texts:
        # Каждая строка вида: "x = expr and n element Z"
        for line in text.split('\n'):
            line = line.strip()
            # Принимаем и точные "x = ...", и численные "x ≈ ..."
            m = re.match(r'^x\s*[=≈]\s*(.+)$', line)
            if not m:
                continue
            # Убираем хвост " and n element Z" и многоточия
            rhs = re.split(r'\s+and\s+', m.group(1), maxsplit=1)[0]
            rhs = re.sub(r'(\.\.\.|…)\s*$', '', rhs).strip()
            if 'root of' in rhs or 'i' == rhs[-1:]:  # неразбираемое/комплексное
                continue

            # π → pi, числа типа "2/3 π" → "2/3*pi", "(3 n - 1)" → "(3*n-1)"
            rhs = rhs.replace('π', 'pi')
            rhs = rhs.replace('tan^(-1)', 'atan').replace('sin^(-1)', 'asin').replace('cos^(-1)', 'acos')
            rhs = rhs.replace('^', '**')
            rhs = re.sub(r'(\d)\s+pi', r'\1*pi', rhs)   # "2 pi" → "2*pi"
            rhs = re.sub(r'pi\s+n\b', r'pi*n', rhs)      # "pi n" → "pi*n"
            rhs = re.sub(r'pi\s+\(', r'pi*(', rhs)       # "pi (" → "pi*("
            rhs = re.sub(r'(\d)\s+n\b', r'\1*n', rhs)    # "3 n" → "3*n"
            rhs = re.sub(r'n\s+(\d)', r'n*\1', rhs)      # "n 2" → "n*2"
            rhs = re.sub(r'(\d)\s+\(', r'\1*(', rhs)     # "2 (" → "2*("
            rhs = re.sub(r'(\d)\s+([-+])', r'\1\2', rhs)

            try:
                expr = sympify(rhs, locals=locals_)
            except Exception:
                continue

            if isinstance(expr, tuple):
                expr = expr[0]

            free = expr.free_symbols
            if n_sym in free:
                for k_val in range(-8, 9):
                    try:
                        val = round(float(expr.subs(n_sym, k_val)), 8)
                        if lo - 1e-9 <= val <= hi + 1e-9:
                            if not any(abs(val - r) < 1e-6 for r in roots):
                                roots.append(val)
                    except Exception:
                        pass
            else:
                try:
                    val = round(float(expr), 8)
                    if lo - 1e-9 <= val <= hi + 1e-9:
                        if not any(abs(val - r) < 1e-6 for r in roots):
                            roots.append(val)
                except Exception:
                    pass

    return sorted(roots) if roots else None


def get_correct_roots(equation_latex: str, use_wolfram: bool = False,
                      prefer_wolfram: bool = False) -> dict:
    if prefer_wolfram and use_wolfram:
        roots = _solve_wolfram(equation_latex)
        if roots is not None:
            return {'method': 'wolfram', 'roots': roots}
    roots = _solve_symbolic(equation_latex)
    if roots is not None:
        return {'method': 'symbolic', 'roots': roots}
    roots = _solve_numeric(equation_latex)
    if roots is not None:
        return {'method': 'numeric', 'roots': roots}
    if use_wolfram and not prefer_wolfram:
        roots = _solve_wolfram(equation_latex)
        if roots is not None:
            return {'method': 'wolfram', 'roots': roots}
    return {'method': 'failed', 'roots': None}


# ──────────────────────────────────────────────
# Замены переменных
# ──────────────────────────────────────────────

def _parse_substitution(latex: str):
    """
    Парсит шаг 'замена': '\\sin x = t' или 't = \\sin x' (+ хвосты '; t > 0').
    Возвращает (имя_переменной, sympy-выражение от x) или None.
    Какая сторона — новая переменная: та, что является одиночной буквой ≠ x.
    """
    s = re.split(r'[;]', latex)[0].strip()
    if '=' not in s:
        return None
    lhs, rhs = s.split('=', 1)
    lhs, rhs = lhs.strip(), rhs.strip()

    def bare_var(p):
        m = re.fullmatch(r'([a-wyzA-Z])', p.strip())
        return m.group(1) if m else None

    var_l, var_r = bare_var(lhs), bare_var(rhs)
    if var_r and not var_l:
        var, expr_latex = var_r, lhs
    elif var_l and not var_r:
        var, expr_latex = var_l, rhs
    else:
        return None

    expr = parse_expr(expr_latex)
    if expr is None or x not in expr.free_symbols:
        return None
    return var, expr


def _check_subst_equation(latex: str, subst_map: dict, correct_roots: list) -> dict:
    """
    уравнение в переменной замены (напр. '-2t^2 + \\sqrt{3}t + 3 = 0'):
    подставляем t → sin(x) и проверяем что все эталонные корни удовлетворяют.
    """
    expr = parse_equation(latex)
    if expr is None:
        return {'checked': False, 'ok': None,
                'reason': 'не удалось распарсить уравнение замены'}

    for var, sub_expr in subst_map.items():
        expr = expr.subs(symbols(var), sub_expr)

    if expr.free_symbols - {x}:
        return {'checked': False, 'ok': None,
                'reason': 'после подстановки замены остались неизвестные переменные'}

    for r in correct_roots:
        try:
            val = float(expr.subs(x, r))
            if abs(val) > 1e-4:
                return {'checked': True, 'ok': False,
                        'reason': f'после обратной замены корень x={r:.4f} не удовлетворяет уравнению'}
        except Exception:
            return {'checked': False, 'ok': None, 'reason': 'ошибка при подстановке'}

    return {'checked': True, 'ok': True,
            'reason': 'уравнение замены верно (все корни удовлетворяют после подстановки)'}


# ──────────────────────────────────────────────
# Проверка арифметики (вычисление)
# ──────────────────────────────────────────────

_BARE_NAME_RE = re.compile(r'[A-Za-z](?:_\{?\w{1,3}\}?)?')


def _check_computation(latex: str) -> dict:
    """
    вычисление — цепочки равенств 'D = 784 - 1080 = -296', 't_1 = (5+3)/2 = 4'.
    Отбрасываем голые имена (D, t_1), сверяем численно остальные части.
    """
    if r'\pm' in latex:
        return {'checked': False, 'ok': None,
                'reason': "вычисление с \\pm — пропускаем"}

    checked_any = False
    # Разбиваем на подвыражения по запятым (не десятичным: за запятой идёт буква/слеш)
    for stmt in re.split(r',\s*(?=[A-Za-z\\])', latex):
        parts = stmt.split('=')
        if len(parts) < 2:
            continue
        vals = []
        parseable = True
        for p in parts:
            p = p.strip()
            if _BARE_NAME_RE.fullmatch(p):
                continue  # голое имя: D, t_1, x_2
            e = parse_expr(p)
            if e is None or e.free_symbols:
                parseable = False
                break
            try:
                vals.append(float(e))
            except Exception:
                parseable = False
                break
        if not parseable or len(vals) < 2:
            continue
        checked_any = True
        if any(abs(vals[0] - v) > 1e-6 for v in vals[1:]):
            return {'checked': True, 'ok': False,
                    'reason': f'арифметическая ошибка: {stmt.strip()[:50]}'}

    if checked_any:
        return {'checked': True, 'ok': True, 'reason': 'арифметика верна'}
    return {'checked': False, 'ok': None,
            'reason': "тип 'вычисление' — нечего проверять численно"}


# ──────────────────────────────────────────────
# Проверка отдельных типов шагов
# ──────────────────────────────────────────────

SYMPY_CHECKABLE = {'преобразование', 'уравнение', 'тригонометрия', 'вычисление'}

# Разделители составных строк: 'sin x = a или sin x = b'
_COMPOSITE_SPLIT_RE = re.compile(r'\s*(?:или|\\quad|\\Leftrightarrow|;)\s*')


def _split_composite(latex: str) -> list:
    # \begin{cases} a \\ b \end{cases} — система/совокупность: ветви через \\
    s = re.sub(r'\\begin\{cases\}|\\end\{cases\}', ' ', latex)
    s = s.replace('\\\\', ' или ')
    parts = [p.strip() for p in _COMPOSITE_SPLIT_RE.split(s) if p.strip()]
    return parts if parts else [latex]


def _check_transformation(latex: str, correct_roots: list) -> dict:
    """
    преобразование / вычисление:
    ВСЕ эталонные корни должны удовлетворять уравнению шага.
    """
    expr = parse_equation(latex)
    if expr is None:
        return {'checked': False, 'ok': None, 'reason': 'не удалось распарсить LaTeX'}

    satisfied, failed = [], []
    for r in correct_roots:
        try:
            val = float(expr.subs(x, r))
            (satisfied if abs(val) < 1e-4 else failed).append(r)
        except Exception:
            return {'checked': False, 'ok': None, 'reason': 'ошибка при подстановке'}

    if not failed:
        return {'checked': True, 'ok': True, 'reason': 'все корни удовлетворяют шагу'}
    if not satisfied:
        return {'checked': True, 'ok': False,
                'reason': f'ни один корень не удовлетворяет шагу (напр. x={failed[0]:.4f})'}

    # Часть корней удовлетворяет. Отличаем ветвь разбора случаев от ошибки:
    # настоящая ветвь только ТЕРЯЕТ корни исходного уравнения, но не приобретает
    # посторонних. Решаем уравнение шага и ищем чужие корни.
    step_roots = _solve_numeric(latex)
    if step_roots:
        lo = min(correct_roots) - 0.1
        hi = max(correct_roots) + 0.1
        alien = [r for r in step_roots if lo <= r <= hi
                 and not any(abs(r - c) < 1e-4 for c in correct_roots)]
        if alien:
            return {'checked': True, 'ok': False,
                    'reason': (f'шаг вводит посторонние корни '
                               f'{[round(r, 4) for r in alien[:4]]} — '
                               f'не следует из исходного уравнения')}
        return {'checked': False, 'ok': None,
                'reason': (f'ветвь разбора случаев: корни шага — подмножество '
                           f'эталонных ({len(satisfied)}/{len(correct_roots)})')}

    # Уравнение шага решить не удалось — оставляем неопределённость
    return {'checked': False, 'ok': None,
            'reason': f'шаг покрывает часть корней ({len(satisfied)}/{len(correct_roots)}) — возможно ветвь разбора случаев'}


def _check_partial_equation(latex: str, correct_roots: list) -> dict:
    """
    уравнение (промежуточное):
    Это может быть один из случаев разбивки (cos x = 0 ИЛИ cos x = 1/2).
    Проверяем что ХОТЯ БЫ ОДИН эталонный корень удовлетворяет,
    и что уравнение не порождает лишних корней вне эталонного множества.
    """
    expr = parse_equation(latex)
    if expr is None:
        return {'checked': False, 'ok': None, 'reason': 'не удалось распарсить LaTeX'}

    # Хотя бы один корень должен удовлетворять
    satisfying = []
    for r in correct_roots:
        try:
            val = float(expr.subs(x, r))
            if abs(val) < 1e-4:
                satisfying.append(r)
        except Exception:
            pass

    if not satisfying:
        return {'checked': True, 'ok': False,
                'reason': 'ни один эталонный корень не удовлетворяет уравнению'}

    return {'checked': True, 'ok': True,
            'reason': f'удовлетворяют корни: {[round(r, 4) for r in satisfying]}'}


def _parse_trig_formula(latex: str) -> list:
    """
    Разворачивает формулу вида x = a + pi*k (k=-4..4) в числовые значения.
    Поддерживает pm и любые однобуквенные параметры (k, n, m, l, p, d).
    """
    has_pm = r'\pm' in latex
    variants = [latex.replace(r'\pm', '+'), latex.replace(r'\pm', '-')] if has_pm else [latex]

    # Все типичные имена параметра
    param_names = ['k', 'n', 'm', 'l', 'p', 'd']
    param_syms  = {name: symbols(name, integer=True) for name in param_names}

    roots = []
    locals_ = {
        'sin': sin, 'cos': cos, 'tan': tan, 'pi': pi,
        'sqrt': sp.sqrt, 'x': x, 'log': sp.log,
        **param_syms,
    }

    for variant in variants:
        if '=' not in variant:
            continue
        _, rhs = variant.split('=', 1)

        # Убираем хвост вида ", k ∈ Z" / "k \in \mathbb{Z}" и всё после запятой+буквы
        rhs = re.sub(r',\s*[a-zA-Z]\s*\\?in\b.*', '', rhs)
        rhs = re.sub(r'\\in\b.*', '', rhs)
        rhs = re.sub(r'\\mathbb\{[A-Z]\}.*', '', rhs)
        # Убираем текстовые пометки \text{...}
        rhs = re.sub(r'\\text\{[^}]*\}', '', rhs)
        # Если после запятой остался параметр без "∈" — тоже убираем
        # Например "... + 2\pi n, n" → убираем ", n"
        rhs = re.sub(r',\s*[a-zA-Z]\s*$', '', rhs.strip())

        rhs_str = latex_to_str(rhs)
        # pi <letter> → pi*<letter>
        rhs_str = re.sub(r'(pi)\s+([a-zA-Z])', r'\1*\2', rhs_str)
        # одиночный параметр перед скобкой: "(-1)**k (pi/6)" → "(-1)**k*(pi/6)"
        rhs_str = re.sub(r'\b([kndmlp])\s*\(', r'\1*(', rhs_str)

        try:
            expr = sympify(rhs_str, locals=locals_)
        except Exception:
            continue

        # Если sympify вернул tuple (e.g. из "a, b") — берём первый элемент
        if isinstance(expr, tuple):
            expr = expr[0]

        # Определяем какой параметр реально используется
        free = expr.free_symbols - {x}
        used = [s for s in free if s.name in param_names]
        if not used:
            # Константа — просто вычисляем
            try:
                val = round(float(expr), 8)
                if not any(abs(val - r) < 1e-6 for r in roots):
                    roots.append(val)
            except Exception:
                pass
            continue

        for param_sym in used:
            for k_val in range(-6, 7):
                try:
                    val = float(expr.subs(param_sym, k_val))
                    val = round(val, 8)
                    if not any(abs(val - r) < 1e-6 for r in roots):
                        roots.append(val)
                except Exception:
                    pass

    return sorted(roots)


def _check_trig_formula(latex: str, correct_roots: list) -> dict:
    """
    тригонометрия (x = ... + pi*k):
    Проверяем что формула порождает подмножество эталонных корней
    (не обязательно все — может быть только один из случаев).
    """
    formula_roots = _parse_trig_formula(latex)
    if not formula_roots:
        return {'checked': False, 'ok': None,
                'reason': 'не удалось распарсить формулу с k'}

    # Проверяем только в диапазоне эталонных корней ± небольшой запас
    lo = min(correct_roots) - 0.1
    hi = max(correct_roots) + 0.1
    formula_in_range = [r for r in formula_roots if lo <= r <= hi]

    # Все корни формулы в этом диапазоне должны быть эталонными
    extra = [r for r in formula_in_range
             if not any(abs(r - e) < 1e-4 for e in correct_roots)]

    if extra:
        return {'checked': True, 'ok': False,
                'reason': f'формула даёт лишние корни: {[round(r, 4) for r in extra]}'}

    matching = [r for r in formula_in_range
                if any(abs(r - e) < 1e-4 for e in correct_roots)]
    if not matching:
        return {'checked': True, 'ok': False,
                'reason': 'формула не покрывает ни одного эталонного корня'}

    return {'checked': True, 'ok': True,
            'reason': f'формула верна, покрывает корни: {[round(r, 4) for r in matching]}'}


def _check_step_by_type(step: dict, correct_roots: list,
                        subst_map: dict = None) -> dict:
    step_type = step.get('type', '')
    latex = step.get('latex', '')
    subst_map = subst_map or {}

    # Вычисление можно проверить и без эталонных корней (чистая арифметика)
    if step_type == 'вычисление':
        return _check_computation(latex)

    if not correct_roots:
        return {'checked': False, 'ok': None,
                'reason': 'нет эталонных корней — передаём в LLM'}

    if step_type == 'преобразование':
        return _check_transformation(latex, correct_roots)

    if step_type == 'уравнение':
        # Уравнение в переменной замены — подставляем t → sin(x) и проверяем
        # (lookbehind/lookahead вместо \b: ловим 't' и в '9t^2', '28t')
        non_x_vars = re.findall(r'(?<![a-zA-Z\\])([tywuvsqrghj])(?![a-zA-Z])', latex)
        if non_x_vars:
            if any(v in subst_map for v in non_x_vars):
                return _check_subst_equation(latex, subst_map, correct_roots)
            return {'checked': False, 'ok': None,
                    'reason': f"уравнение в переменной '{non_x_vars[0]}' без известной замены — пропускаем"}
        # Составная строка 'sin x = a или sin x = b': верна, если хотя бы одна
        # часть удовлетворяется эталонными корнями
        parts = _split_composite(latex)
        if len(parts) > 1:
            results = [_check_partial_equation(p, correct_roots) for p in parts]
            if any(r['checked'] and r['ok'] for r in results):
                return {'checked': True, 'ok': True,
                        'reason': 'одна из ветвей уравнения удовлетворяется корнями'}
            if all(r['checked'] for r in results):
                return {'checked': True, 'ok': False,
                        'reason': 'ни одна ветвь уравнения не удовлетворяется корнями'}
            return {'checked': False, 'ok': None,
                    'reason': 'составное уравнение — не все ветви распарсились'}
        return _check_partial_equation(latex, correct_roots)

    if step_type == 'тригонометрия':
        # Если слева не 'x' / 'x_1', а выражение (cos x = 1/2, 9^{cos x} = 1/9) —
        # это промежуточное уравнение, а не формула корней
        lhs = latex.split('=', 1)[0].strip() if '=' in latex else ''
        if lhs and not re.fullmatch(r'x(?:_\{?\d\}?)?', lhs):
            return _check_partial_equation(latex, correct_roots)
        # Составная строка: объединяем корни всех ветвей
        parts = _split_composite(latex)
        if len(parts) > 1:
            results = [_check_trig_formula(p, correct_roots) for p in parts]
            if any(r['checked'] and r['ok'] for r in results):
                return {'checked': True, 'ok': True,
                        'reason': 'одна из ветвей формулы верна'}
            if any(r['checked'] and r['ok'] is False for r in results):
                bad = next(r for r in results if r['checked'] and r['ok'] is False)
                return {'checked': True, 'ok': False, 'reason': bad['reason']}
            return {'checked': False, 'ok': None,
                    'reason': 'составная формула — ветви не распарсились'}
        return _check_trig_formula(latex, correct_roots)

    # замена, ОДЗ, ответ — только LLM
    return {'checked': False, 'ok': None,
            'reason': f"тип '{step_type}' — передаём в LLM"}


# ──────────────────────────────────────────────
# Сравнение ответов
# ──────────────────────────────────────────────

def _parse_student_roots(answer_str: str) -> list:
    s = answer_str.replace('π', 'pi').replace(r'\pi', 'pi')
    tokens = re.findall(
        r'[-+]?\s*\d*\.?\d*\s*\*?\s*pi\s*/\s*\d+|[-+]?\s*\d+\.?\d*', s
    )
    roots = []
    for tok in tokens:
        tok = tok.replace(' ', '')
        try:
            val = round(float(eval(tok.replace('pi', str(math.pi)))), 8)
            roots.append(val)
        except Exception:
            pass
    return sorted(roots)


def compare_roots(student_answer: str, correct_roots: list) -> dict:
    # Случайно удвоенные слеши из ручных правок CSV: \\frac → \frac
    student_answer = re.sub(r'\\\\(?=[a-zA-Z])', r'\\', student_answer)
    # Маркеры пунктов "а)", "б)", "a)", "b)" в начале и внутри
    student_answer = re.sub(r'(?:^|[;,]\s*)[абвab]\)\s*', ' ', student_answer)
    # "Ответ:" и подобные подписи
    student_answer = re.sub(r'(?:Ответ|ответ)\s*:?', ' ', student_answer)
    # Ответ может содержать несколько формул через запятую
    # Разбиваем по запятой, но только там где после запятой идёт 'x ='
    # Простой способ: split по ', x =' или по '\n'
    # Сначала раскрываем \begin{cases}...\end{cases} и разделители «или»/;/\\
    pre_parts = _split_composite(student_answer)
    parts = []
    for p in pre_parts:
        parts.extend(re.split(r',\s*(?=x\s*=)', p))
    # Хвосты вида "k \in Z" без x= — отбрасываем
    parts = [p for p in parts if '=' not in p or re.search(r'x', p)]
    if not parts:
        parts = [student_answer]

    student_roots = []
    for part in parts:
        part = part.strip()
        if '=' not in part:
            part = 'x = ' + part
        roots_part = _parse_trig_formula(part)
        if roots_part:
            student_roots.extend(roots_part)

    if not student_roots:
        # fallback: числа напрямую (для ответов типа "pi/4")
        student_roots = _parse_student_roots(student_answer)

    # Проверяем покрытие в диапазоне эталонных корней
    lo = min(correct_roots) - 0.1
    hi = max(correct_roots) + 0.1
    student_in_range = [r for r in student_roots if lo <= r <= hi]

    missing = [r for r in correct_roots
               if not any(abs(r - s) < 1e-4 for s in student_in_range)]
    extra   = [s for s in student_in_range
               if not any(abs(s - r) < 1e-4 for r in correct_roots)]
    return {
        'student_roots': student_in_range,
        'correct_roots': correct_roots,
        'missing_roots': missing,
        'extra_roots':   extra,
        'is_correct':    len(missing) == 0 and len(extra) == 0,
    }


# ──────────────────────────────────────────────
# Главная функция
# ──────────────────────────────────────────────

def check_solution_recovered(equation_latex: str,
                             steps: list,
                             student_answer: str,
                             use_wolfram: bool = False) -> dict:
    """
    check_solution + восстановление условия по шагам.

    Если проверка с уравнением из первой строки не даёт уверенной единицы,
    пробуем взять эталоном первые шаги решения: когда шаги и ответ согласованы
    между собой, но противоречат условию, вероятна описка ученика при
    переписывании условия или ошибка распознавания. По критериям ЕГЭ описка
    в условии при верной последовательности шагов не критична.
    """
    res = check_solution(equation_latex, steps, student_answer,
                         use_wolfram=use_wolfram)
    if res['score'] == 1:
        return res

    for i, step in enumerate(steps[:3]):
        if step.get('type') not in ('преобразование', 'уравнение'):
            continue
        cand = step.get('latex', '')
        if '=' not in cand or 'x' not in cand:
            continue
        if re.sub(r'\s+', '', cand) == re.sub(r'\s+', '', equation_latex):
            continue
        try:
            res2 = check_solution(cand, steps[i + 1:], student_answer,
                                  use_wolfram=use_wolfram)
        except Exception:
            continue
        if res2['score'] == 1:
            # Не выносим вердикт сами: описку в условии от реальной ошибки
            # первого перехода отличит только человек/LLM по фото.
            # Возвращаем ИСХОДНУЮ проверку (с её уликами) + заметку.
            res['score'] = None
            res['needs_llm'] = True
            res['condition_recovered'] = {
                'original': equation_latex,
                'used_step': cand,
                'step_index': i,
            }
            return res

    return res


def check_solution(equation_latex: str,
                   steps: list,
                   student_answer: str,
                   use_wolfram: bool = False,
                   prefer_wolfram: bool = False) -> dict:
    """
    steps — список dict: {'type': str, 'latex': str, 'comment': str}
    prefer_wolfram — Wolfram первым, sympy как fallback
    use_wolfram — разрешить Wolfram; реально он вызывается только если
                  логрег-классификатор относит уравнение к типу 'mixed'
    """
    if use_wolfram:
        use_wolfram = classify_equation_type(equation_latex) == 'mixed'
    root_info = get_correct_roots(equation_latex, use_wolfram=use_wolfram,
                                  prefer_wolfram=prefer_wolfram)
    correct_roots = root_info.get('roots')

    # Дополняем эталонные корни: sympy может пропустить семейство корней
    # (напр. касание нуля без смены знака). Кандидаты из формул ученика
    # проверяем прямой подстановкой в исходное уравнение.
    orig_expr = parse_equation(equation_latex)
    if correct_roots and orig_expr is not None:
        candidates = []
        for step in steps:
            if step.get('type', '') in ('тригонометрия', 'ответ'):
                for part in _split_composite(step.get('latex', '')):
                    candidates.extend(_parse_trig_formula(part))
        for part in re.split(r',\s*(?=x\s*=)', student_answer or ''):
            part = part.strip()
            if part:
                candidates.extend(_parse_trig_formula(part if '=' in part else 'x = ' + part))

        lo, hi = min(correct_roots) - 0.1, max(correct_roots) + 0.1
        for v in candidates:
            if not (lo <= v <= hi):
                continue
            if any(abs(v - r) < 1e-6 for r in correct_roots):
                continue
            try:
                if abs(float(orig_expr.subs(x, v))) < 1e-4:
                    correct_roots.append(v)
            except Exception:
                pass
        correct_roots = sorted(correct_roots)

    # Пре-проход: собираем замены переменных (sin x = t и т.п.)
    subst_map = {}
    for step in steps:
        if step.get('type', '') == 'замена':
            parsed = _parse_substitution(step.get('latex', ''))
            if parsed:
                subst_map[parsed[0]] = parsed[1]

    step_results = []
    unchecked = []
    has_sympy_error = False

    for i, step in enumerate(steps):
        check = _check_step_by_type(step, correct_roots or [], subst_map)
        entry = {
            'index':   i,
            'type':    step.get('type', ''),
            'latex':   step.get('latex', ''),
            'comment': step.get('comment', ''),
            **check,
        }
        step_results.append(entry)

        step_type = step.get('type', '')
        if not check['checked']:
            # Эти типы не блокируют sympy-вердикт
            skip_types = ('замена', 'ОДЗ', 'ответ', 'вычисление')
            is_skipped_equation = (
                step_type == 'уравнение' and
                'переменной' in check.get('reason', '')
            )
            if step_type not in skip_types and not is_skipped_equation:
                unchecked.append(i)
        elif check['ok'] is False:
            has_sympy_error = True

    answer_check = None
    if correct_roots:
        # OCR иногда раскладывает семейства корней между полем answer и
        # шагами типа "ответ" — объединяем их перед сверкой
        answer_full = student_answer or ''
        for step in steps:
            if step.get('type') == 'ответ' and '=' in step.get('latex', ''):
                answer_full += ', ' + step['latex']
        answer_check = compare_roots(answer_full, correct_roots)

    answer_ok = bool(answer_check and answer_check['is_correct'])

    # Ослабленный критерий:
    #  - ответ верен + ни одной найденной ошибки в шагах → 1
    #    (даже если часть шагов не покрыта проверкой — финальный ответ сверен)
    #  - ответ неверен + все шаги покрыты → 0
    #  - есть ошибка в шаге + ответ неверен → 0
    #  - остальное (противоречия, нет эталонных корней) → LLM
    if correct_roots is None or answer_check is None:
        score = None
    elif answer_ok and not has_sympy_error:
        score = 1
    elif not answer_ok and has_sympy_error:
        score = 0
    elif not answer_ok and len(unchecked) == 0:
        score = 0
    else:
        score = None

    needs_llm = score is None

    return {
        'score':           score,
        'solver_method':   root_info['method'],
        'correct_roots':   correct_roots,
        'step_results':    step_results,
        'answer_check':    answer_check,
        'needs_llm':       needs_llm,
        'unchecked_steps': unchecked,
    }
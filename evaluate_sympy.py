

import sys
import json
import re
import pandas as pd
from pathlib import Path
from sklearn.metrics import f1_score, classification_report

from checker_v2 import check_solution, latex_to_str

USE_WOLFRAM = '--wolfram' in sys.argv

INPUT_CSV  = Path("results.csv")
OUTPUT_CSV = Path("results_sympy_wolfram.csv") if USE_WOLFRAM else Path("results_sympy.csv")


# ──────────────────────────────────────────────
# Нормализация LaTeX перед подачей в checker
# ──────────────────────────────────────────────

def normalize_latex(s: str) -> str:
    """Дополнительная нормализация поверх latex_to_str из checker_v2."""
    if not s:
        return s

    # \text{...} — убираем обёртку, оставляем содержимое
    s = re.sub(r'\\text\{([^}]*)\}', r'\1', s)

    # \quad, \qquad — пробелы
    s = re.sub(r'\\q?quad', ' ', s)

    # \implies, \Rightarrow, \Leftrightarrow → =
    s = re.sub(r'\\implies|\\Rightarrow|\\Leftrightarrow|\\Longrightarrow', '=', s)

    # Убираем \mathbb{Z}, \mathbb{R} и подобное
    s = re.sub(r'\\mathbb\{[A-Z]\}', '', s)

    # \notin, \in — убираем (не нужны для парсинга уравнения)
    s = re.sub(r'\\(?:not)?in\b', '', s)

    # \pm → + (для основной ветки; _parse_trig_formula сам обрабатывает \pm)
    # Не заменяем здесь — оставляем для _parse_trig_formula

    # Несколько пробелов → один
    s = re.sub(r'  +', ' ', s)

    return s.strip()


def normalize_equation(eq: str) -> str:
    return normalize_latex(eq)


def normalize_answer(ans: str) -> str:
    return normalize_latex(ans)


def normalize_steps(steps: list) -> list:
    result = []
    for step in steps:
        result.append({
            'type':    step.get('type', ''),
            'latex':   normalize_latex(step.get('latex', '')),
            'comment': step.get('comment', ''),
        })
    return result


# ──────────────────────────────────────────────
# Запуск sympy-only проверки
# ──────────────────────────────────────────────

def run_sympy_check(equation: str, steps: list, answer: str, use_wolfram: bool = False) -> dict:
    """
    Запускает check_solution и возвращает:
      score        : 0, 1 или None (если sympy не смог)
      needs_llm    : bool
      solver_method: str
      errors       : список ошибочных шагов
    """
    try:
        result = check_solution(equation, steps, answer, use_wolfram=use_wolfram)
        errors = [
            f"[{s['type']}] {s['reason']}"
            for s in result.get('step_results', [])
            if s.get('ok') is False
        ]
        return {
            'score':         result['score'],
            'needs_llm':     result['needs_llm'],
            'solver_method': result['solver_method'],
            'errors':        '; '.join(errors),
        }
    except Exception as e:
        return {
            'score':         None,
            'needs_llm':     True,
            'solver_method': 'error',
            'errors':        str(e),
        }


# ──────────────────────────────────────────────
# F1 отчёт
# ──────────────────────────────────────────────

def print_metrics(label: str, y_true, y_pred):
    f1  = f1_score(y_true, y_pred, zero_division=0)
    acc = (y_true == y_pred).mean()
    print(f"\n  [{label}]  N={len(y_true)}  Acc={acc:.3f}  F1={f1:.3f}")
    print(classification_report(y_true, y_pred, target_names=['0','1'], zero_division=0))


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    df = pd.read_csv(INPUT_CSV, encoding='utf-8-sig')

    # Убираем строки-метрики
    df = df[~df['image'].astype(str).str.startswith('---')].copy()
    df = df[df['ground_truth'].notna() & (df['ground_truth'] != '')].copy()
    df['ground_truth'] = df['ground_truth'].astype(int)

    print(f"Загружено строк с GT: {len(df)}  |  Wolfram: {'ON' if USE_WOLFRAM else 'OFF'}")

    rows = []

    for i, (_, row) in enumerate(df.iterrows(), 1):
        image    = row['image']
        equation = normalize_equation(str(row.get('equation', '') or ''))
        answer   = normalize_answer(str(row.get('answer', '') or ''))
        gt       = int(row['ground_truth'])

        # Парсим шаги из JSON (с починкой сломанного экранирования после ручных правок)
        raw = row.get('latex_ocr', '') or '[]'
        try:
            raw_steps = json.loads(raw)
        except Exception:
            try:
                from pipeline import _repair_json
                raw_steps = json.loads(_repair_json(raw))
            except Exception:
                raw_steps = []
        steps = normalize_steps(raw_steps)

        print(f"[{i}/{len(df)}] {image}  eq={equation[:60]}")

        check = run_sympy_check(equation, steps, answer, use_wolfram=USE_WOLFRAM)
        score = check['score']

        out = {
            'image':         image,
            'equation':      equation,
            'answer':        answer,
            'ground_truth':  gt,
            'sympy_score':   score if score is not None else -1,
            'needs_llm':     check['needs_llm'],
            'solver_method': check['solver_method'],
            'sympy_errors':  check['errors'],
        }
        rows.append(out)

    result_df = pd.DataFrame(rows)
    result_df.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')

    # ── Метрики ──
    certain  = result_df[result_df['sympy_score'] != -1].copy()
    all_rows = result_df.copy()

    print(f"\n{'='*60}")
    print(f"  Всего: {len(result_df)}  |  sympy дал балл: {len(certain)}  |  needs_llm: {(result_df['sympy_score']==-1).sum()}")

    if len(certain) > 0:
        print_metrics(
            "sympy certain only",
            certain['ground_truth'],
            certain['sympy_score'],
        )

    # Uncertain → 0
    pred_0 = all_rows['sympy_score'].replace(-1, 0)
    print_metrics("uncertain→0", all_rows['ground_truth'], pred_0)

    # Uncertain → 1
    pred_1 = all_rows['sympy_score'].replace(-1, 1)
    print_metrics("uncertain→1", all_rows['ground_truth'], pred_1)

    print(f"\nРезультаты: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()

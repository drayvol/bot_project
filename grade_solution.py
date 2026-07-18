"""
grade_solution.py — точка входа для бота: оценка фото решения задания №13.

Конвейер:
  фото → OCR (дословная транскрипция) → пользовательское подтверждение (опц.)
       → формальный чекер (sympy + Wolfram + логрег-маршрутизация)
       → чекер уверен в 1 → балл без LLM
       → иначе → Gemma: фото + отчёт чекера (FORMAL VERIFICATION)

Использование из бота:

    from grade_solution import Grader

    grader = Grader()                       # ключи из окружения

    # Шаг 1: распознать (показать пользователю на подтверждение)
    ocr = grader.recognize('photo.jpg')     # {'equation', 'steps', 'answer'}

    # Шаг 2 (опц.): пользователь исправил ocr['equation'] / steps / answer

    # Шаг 3: оценить
    result = grader.grade('photo.jpg', ocr)
    # result: {'score': 0|1|None, 'verdict_source': 'checker'|'gemma',
    #          'checker_score', 'suspicious_ocr': bool, 'llm_comment', ...}

    # Бонус: похожие задачи с решениями
    similar = grader.similar_tasks(ocr['equation'], top_k=3)

Ключи окружения: GOOGLE_API_KEY (обязательно), WOLFRAM_API_KEY (опционально).
"""

import os
import time
import warnings
warnings.filterwarnings('ignore')

from google import genai
from google.genai import types as genai_types

from checker_v2 import check_solution_recovered
from pipeline import ocr_image, build_checker_report, formal_verification
from evaluate import extract_score_from_verification
from evaluate_sympy import normalize_latex, normalize_steps


def _with_retries(fn, tries=4, base_wait=20):
    last = None
    for attempt in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            time.sleep(base_wait * (attempt + 1))
    raise last


class Grader:
    def __init__(self, api_key: str = None):
        self.client = genai.Client(
            api_key=api_key or os.environ['GOOGLE_API_KEY'],
            http_options=genai_types.HttpOptions(timeout=180_000),
        )

    # ── Шаг 1: распознавание ──
    def recognize(self, image_path: str) -> dict:
        """OCR решения. Результат можно показать пользователю на подтверждение."""
        return _with_retries(lambda: ocr_image(image_path, self.client))

    # ── Шаг 3: оценка ──
    def grade(self, image_path: str, ocr: dict = None) -> dict:
        """
        Полная оценка. Если ocr не передан — распознаёт сам.
        ocr может быть отредактирован пользователем (исправление сканирования).
        """
        if ocr is None:
            ocr = self.recognize(image_path)

        steps = normalize_steps(ocr.get('steps', []))
        eq = normalize_latex(str(ocr.get('equation', '') or ''))
        ans = normalize_latex(str(ocr.get('answer', '') or ''))

        use_wolfram = bool(os.environ.get('WOLFRAM_API_KEY'))
        try:
            res = check_solution_recovered(eq, steps, ans, use_wolfram=use_wolfram)
        except Exception:
            res = {'score': None, 'solver_method': 'error', 'step_results': [],
                   'correct_roots': None, 'answer_check': None}

        checker_score = res['score'] if res['score'] is not None else None
        suspicious = bool(res.get('condition_recovered')) or res['solver_method'] in ('failed', 'error')

        out = {
            'equation': ocr.get('equation', ''),
            'answer': ocr.get('answer', ''),
            'checker_score': checker_score,
            'solver_method': res['solver_method'],
            'suspicious_ocr': suspicious,     # стоит переспросить пользователя
            'step_results': res.get('step_results', []),
            'llm_comment': None,
        }

        if checker_score == 1:
            out['score'] = 1
            out['verdict_source'] = 'checker'
            return out

        # Gemma с отчётом чекера
        report = build_checker_report(res, eq, ans)
        verif = _with_retries(lambda: formal_verification(
            image_path, self.client, checker_report=report))
        score = extract_score_from_verification(verif or '')
        out['score'] = score
        out['verdict_source'] = 'gemma'
        out['llm_comment'] = verif
        return out

    # ── Похожие задачи ──
    def similar_tasks(self, equation_latex: str, top_k: int = 3) -> list:
        """Похожие задачи с решениями из векторной базы (Qdrant)."""
        from search_equations import search
        return search(equation_latex, top_k=top_k)


if __name__ == '__main__':
    import sys
    g = Grader()
    r = g.grade(sys.argv[1])
    print(f"Балл: {r['score']} (источник: {r['verdict_source']})")
    print(f"Уравнение: {r['equation']}")
    if r['suspicious_ocr']:
        print("⚠ распознавание сомнительно — стоит показать пользователю")

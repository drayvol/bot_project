"""
pipeline.py
Пайплайн: фото → OCR (Gemma, типизированные шаги) → checker_v2 → FORMAL VERIFICATION LLM
"""

import os
import re
import json
import argparse
from pathlib import Path

from google import genai
from google.genai import types

from core.checker_v2 import check_solution

GEMMA_MODEL = "gemma-4-26b-a4b-it"

# ──────────────────────────────────────────────
# Промпты
# ──────────────────────────────────────────────

OCR_SYSTEM_PROMPT = """Ты — математический OCR и аналитик решений ЕГЭ.
На фото — рукописное решение тригонометрического уравнения.

Извлеки решение и верни ТОЛЬКО валидный JSON без markdown-блоков:

{
  "equation": "<исходное уравнение в LaTeX>",
  "steps": [
    {
      "type": "<тип шага>",
      "latex": "<математическое выражение шага в LaTeX>",
      "comment": "<краткое описание что сделано, 5-8 слов>"
    }
  ],
  "answer": "<финальный ответ в LaTeX>"
}

Допустимые типы шагов (type) — выбирай наиболее точный:
- "преобразование"  — алгебраическое или логарифмическое преобразование выражения
- "замена"          — введение новой переменной (замена sin x = t и т.п.)
- "уравнение"       — промежуточное уравнение или система уравнений
- "вычисление"      — арифметика, дискриминант, числовая подстановка
- "ОДЗ"             — проверка области допустимых значений
- "тригонометрия"   — обратная замена, арксинус/арккосинус, общая формула корней
- "ответ"           — финальный ответ или отбор корней

Правила:
- Каждый шаг — ОДНО математическое действие
- Если строка зачёркнута — всё равно включи, добавь в comment "(зачёркнуто)"
- LaTeX: \\sin, \\cos, \\frac{a}{b}, \\sqrt{}, \\pi, \\begin{cases}...\\end{cases}
- comment пиши по-русски
- Не придумывай шаги которых нет на фото
- КРИТИЧЕСКИ ВАЖНО: переписывай В ТОЧНОСТИ то, что написано на фото,
  ДАЖЕ ЕСЛИ ученик ошибся. НИКОГДА не исправляй математику ученика.
  Это система проверки решений: если ученик написал "8 = 4\\sin x" —
  пиши "8 = 4\\sin x", а не "16 = 4\\sin x"; если написал
  "x = -\\frac{\\pi}{4} + 2\\pi k" — пиши с 2\\pi k, а не \\pi k.
  Ошибка ученика на фото — это данные, которые нужно сохранить.
- Отличай СВОЮ неуверенность в прочтении от ошибки ученика: если символ
  плохо читается (например, знаменатель дроби 3 или 6, степень 2 или 3),
  используй контекст решения, чтобы прочитать его верно
  (ученик пишет \\cos\\frac{\\pi}{6} = \\frac{\\sqrt{3}}{2} в шаге —
  значит, в условии \\frac{\\pi}{6}). Но если символ написан ЧЁТКО —
  переписывай как есть, даже если это ошибка ученика.
- Рукописный знак корня \\sqrt легко спутать с цифрой 5. В задачах ЕГЭ
  коэффициенты — маленькие числа и корни (\\sqrt{2}, 2\\sqrt{2}, \\sqrt{3}).
  Если ты прочитал неправдоподобный коэффициент (52, 252, 452 и т.п.) —
  это почти наверняка выражение с корнем: 52 → \\sqrt{2}, 252 → 2\\sqrt{2},
  453 → 4\\sqrt{3}. Перечитай такие места.
- ВАЖНО: основания логарифмов в задачах ЕГЭ — всегда числа (2, 3, 9, 10). Если видишь символ похожий на "g" или "q" рядом с \\log — это цифра 9. Всегда пиши \\log_{9}, никогда \\log_{g}.
- Если на фото НЕТ решения уравнения — посторонний предмет, человек,
  пейзаж, пустой лист, печатный текст без уравнения, скриншот переписки,
  задача без уравнения (геометрия, текстовая) и т.п. — верни ровно:
  {"not_math": true, "reason": "<что на фото, 3-6 слов>",
   "equation": "", "steps": [], "answer": ""}
  Не пытайся извлечь уравнение из того, чего нет.
"""

FORMAL_VERIFICATION_PROMPT = """FORMAL VERIFICATION.

Ты — ведущий эксперт ЕГЭ по профильной математике.
Ты проверяешь решение задания №13 как официальный эксперт ЕГЭ.

ТВОЯ ЗАДАЧА:
Не решать задачу заново, а проводить строгую проверку решения ученика.

ПРАВИЛА ПРОВЕРКИ:
1. Проверяй КАЖДОЕ преобразование отдельно.
2. Проверяй:
   - эквивалентность переходов;
   - знаки;
   - формулы приведения;
   - ОДЗ;
   - потерю или появление корней;
   - логичность отбора корней;
   - корректность оформления ответа.
3. Не пропускай мелкие ошибки в знаках.
4. Не доверяй автоматически преобразованиям ученика.
5. Если шаг неверен — объясни конкретно, почему.
6. Если шаг верен относительно уже ошибочного уравнения —
   укажи это отдельно.
7. Не приписывай ученику ошибок, которых нет.
8. Не используй эмоциональные фразы:
   - "с потолка"
   - "бред"
   - "очевидно"
   и подобные.
9. Не делай предположений о промежутке,
   если его нет на изображении.
10. Перед выводом перепроверь собственный анализ на противоречия.

КРИТЕРИИ ОЦЕНИВАНИЯ:
- 1 балл — решение полностью верное.
- 0 баллов — решение приводит к неверному ответу
  или содержит критическую ошибку в преобразованиях.
- Оценивается ТОЛЬКО решение уравнения (пункт а).
  Отбор корней на промежутке (пункт б) НЕ входит в проверку:
  его отсутствие или неполнота НЕ снижают балл.
  Если уравнение решено верно, ставь 1 балл, даже если отбор
  корней не выполнен или выполнен с ошибкой.
- ОПИСКА ПРИ ПЕРЕПИСЫВАНИИ УСЛОВИЯ — НЕ ОШИБКА. Ученик переписывает
  условие с бланка задания и может пропустить символ (например, "cos")
  или исказить число. Если дальнейшее решение однозначно показывает,
  что ученик решал ПРАВИЛЬНОЕ уравнение (его первый переход — корректное
  преобразование правильного условия, а не переписанного с опиской),
  то описка в первой строке НЕ критическая ошибка, балл НЕ снижается.
  Признак описки: "переход" из строки 1 в строку 2 выглядит неэквивалентным,
  но строка 2 — это точное раскрытие/преобразование условия БЕЗ описки.
- Небрежность записи, не влияющая на итоговые корни
  (например, ученик назвал √D буквой D, пропустил "=0",
  сокращённые обозначения), — НЕ критическая ошибка.
- Рукописные 3 и 6 (а также 2 и 7) легко перепутать при чтении.
  Если числовые значения тригонометрических функций в шагах ученика
  соответствуют ДРУГОМУ аргументу (например, в условии читается
  \\frac{\\pi}{3}, но ученик подставляет \\cos\\frac{\\pi}{6} =
  \\frac{\\sqrt{3}}{2}), почти наверняка в условии именно тот аргумент,
  значения которого использованы. Перечитай условие с этой гипотезой,
  а не объявляй подстановку ошибкой.
- ПРАВИЛО ОДНОГО СИМВОЛА: если найденная тобой «ошибка» ученика сводится
  к одному трудночитаемому символу — потерян минус перед дробью,
  потеряна «2» в периоде «+2\\pi k» (рукописная 2 похожа на «д»),
  перепутаны 3 и 6, — а во всём остальном серия корней ВЕРНА для
  решаемого простейшего уравнения, то с большой вероятностью символ
  на фото ЕСТЬ, а ошибка — твоя ошибка чтения. Перечитай это место;
  сомневаешься — трактуй в пользу ученика.
- ЗАЩИТА ОТ ОШИБОК ЧТЕНИЯ РУКОПИСИ: если формальный отчёт
  говорит, что финальный ответ ученика СОВПАДАЕТ с эталонными
  корнями и ни один шаг не помечен ✗, а ты видишь на фото
  "ошибку" — с высокой вероятностью ты неверно прочитал
  рукопись (перепутал порядок колонок, увидел лишний символ).
  Перечитай спорное место. Ставь 0 в такой ситуации только если
  можешь объяснить, почему при найденной тобой ошибке финальный
  ответ всё равно совпал с верным.

ФОРМАТ ОТВЕТА:

1. Итоговый балл.
2. Первая критическая ошибка.
3. Какие шаги были верными.
4. Какие шаги неверны.
5. Влияет ли ошибка на итоговый ответ.
6. Корректное решение или корректный фрагмент решения.
7. Краткий итог как эксперт ЕГЭ.

ВАЖНО:
Ты работаешь в режиме FORMAL VERIFICATION,
а не в режиме обычного решения задачи.
Главная цель — строгая математическая корректность.

ФОРМАЛЬНЫЕ ДАННЫЕ:
Вместе с фото тебе передаётся отчёт автоматической проверки
(символьный решатель sympy + Wolfram Alpha):
- эталонные корни исходного уравнения, найденные решателем;
- результат сверки финального ответа ученика с эталонными корнями;
- построчная проверка шагов (✓ верен / ✗ ошибка / ⚠ не проверялся).
Используй эти данные как опору:
- эталонным корням можно доверять;
- пометка ✗ у шага — сильный сигнал ошибки, но перепроверь сам:
  автопроверка иногда ошибается на неэквивалентных, но легитимных
  переходах (разбор случаев, домножение, отбор корней);
- пометка ⚠ означает, что шаг надо проверить полностью самому.
Если отчёт противоречит твоему анализу — разберись, кто прав,
и объясни это в выводе.
"""


def build_checker_report(result: dict, equation: str, answer: str) -> str:
    """Отчёт формальной проверки для передачи в LLM."""
    lines = [
        "ОТЧЁТ АВТОМАТИЧЕСКОЙ ПРОВЕРКИ",
        f"Уравнение (OCR): {equation}",
        f"Ответ ученика (OCR): {answer}",
        f"Решатель: {result['solver_method']}",
    ]

    rec = result.get('condition_recovered')
    if rec:
        lines.append(
            "!!! ГЛАВНЫЙ ФАКТ ПРОВЕРКИ !!!\n"
            "Формальная проверка установила: записанное условие ПРОТИВОРЕЧИТ "
            f"дальнейшим шагам, но начиная с шага {rec['step_index'] + 1} "
            "ВСЁ решение внутренне согласовано и финальный ответ ВЕРЕН для "
            f"уравнения «{rec['used_step']}».\n"
            "Такая картина почти всегда означает описку при переписывании "
            "условия или ошибку распознавания первой строки — ученик РЕШАЛ "
            "правильное уравнение. По критериям это НЕ ошибка (балл 1).\n"
            "Балл 0 ставь ТОЛЬКО если убеждён, что условие на фото записано "
            "чётко и без описки, и ученик действительно потерял слагаемое/знак "
            "в первом переходе. Сомневаешься в прочтении символа (3 или 6, "
            "наличие cos) — трактуй в пользу согласованности решения."
        )

    roots = result.get('correct_roots')
    if roots:
        shown = ', '.join(f"{r:.4f}" for r in roots[:12])
        lines.append(f"Эталонные корни на [-2π, 4π]: {shown}")
    else:
        lines.append("Эталонные корни: решатель НЕ смог решить уравнение "
                     "(возможно, OCR исказил условие — сверь уравнение с фото).")

    ac = result.get('answer_check')
    if ac:
        lines.append(f"Сверка ответа: {'СОВПАДАЕТ с эталонными корнями' if ac['is_correct'] else 'НЕ совпадает'}")
        if ac['missing_roots']:
            lines.append(f"  пропущенные корни: {[round(r, 4) for r in ac['missing_roots'][:8]]}")
        if ac['extra_roots']:
            lines.append(f"  лишние корни: {[round(r, 4) for r in ac['extra_roots'][:8]]}")

    lines.append("Проверка шагов:")
    for s in result.get('step_results', []):
        if s['checked'] and s['ok'] is True:
            mark = '✓'
        elif s['checked'] and s['ok'] is False:
            mark = '✗'
        else:
            mark = '⚠'
        lines.append(f"  [{mark}] ({s['type']}) {s['latex']}")
        if mark != '✓':
            lines.append(f"        причина: {s['reason']}")

    return '\n'.join(lines)


# ──────────────────────────────────────────────
# OCR
# ──────────────────────────────────────────────

def _repair_json(raw: str) -> str:
    """
    Два вида поломок от модели:
    1. "latex "\\sin x = t"  →  "latex": "\\sin x = t"
       (пробел вместо двоеточия перед значением)
    2. Невалидные escape-последовательности внутри JSON-строк:
       c, b, f, n, p и т.д. от LaTeX команд (cdot, begin, frac…)
       JSON разрешает только: \\", \\\\, \\/, \\b, \\f, \\n, \\r, \\t, \\uXXXX
       Все прочие одиночные слеши нужно заменить на двойные.
    """
    # Фикс 1: "ключ " → "ключ":
    keys = "latex|type|comment|equation|answer|steps"
    fixed = re.sub(rf'"({keys}) "', r'"\1": "', raw)

    # Фикс 1.2: двоеточие внутри кавычек ключа: "latex: "значение" → "latex": "значение"
    # (валидное "latex": не матчится — там кавычка закрывается до двоеточия)
    fixed = re.sub(rf'"({keys}):\s*"', r'"\1": "', fixed)

    # Фикс 1.5: пропущена открывающая кавычка значения: "latex": \begin{...}
    fixed = re.sub(rf'"({keys})":\s*\\', r'"\1": "\\', fixed)

    # Фикс 2: одиночные обратные слеши перед LaTeX-командами → двойные
    # Работаем посимвольно внутри JSON-строк чтобы не трогать уже удвоенные \\
    def fix_escapes(s: str) -> str:
        result = []
        i = 0
        while i < len(s):
            ch = s[i]
            if ch == '\\':
                if i + 1 < len(s):
                    nxt = s[i + 1]
                    # Уже удвоенный слеш — оставляем как есть
                    if nxt == '\\':
                        result.append('\\\\')
                        i += 2
                        continue
                    # Допустимые JSON escape: " / b f n r t u
                    if nxt in ('"', '/', 'b', 'f', 'n', 'r', 't', 'u'):
                        result.append(ch)
                        result.append(nxt)
                        i += 2
                        continue
                    # Всё остальное (LaTeX команды) — удваиваем слеш
                    result.append('\\\\')
                    # nxt остаётся, обработается на следующей итерации
                    i += 1
                    continue
                else:
                    result.append('\\\\')
                    i += 1
            else:
                result.append(ch)
                i += 1
        return ''.join(result)

    fixed = fix_escapes(fixed)
    return fixed

def ocr_image(image_path: str, client: genai.Client) -> dict:
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    print("  Загружаю файл в Google Files API...")
    my_file = client.files.upload(file=str(path))

    response = client.models.generate_content(
        model=GEMMA_MODEL,
        contents=[my_file, "Распознай решение и верни JSON."],
        config=types.GenerateContentConfig(
            system_instruction=OCR_SYSTEM_PROMPT,
            temperature=0.1,
        ),
    )

    raw = response.text.strip()

    # Убираем markdown-обёртку
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    # Пробуем распарсить как есть
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Пробуем починить и распарсить ещё раз
    repaired = _repair_json(raw)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        print(f"[OCR] Сырой ответ модели:\n{raw}\n")
        print(f"[OCR] После repair:\n{repaired}\n")
        raise ValueError(f"Невалидный JSON от модели (даже после repair): {e}") from e


# ──────────────────────────────────────────────
# FORMAL VERIFICATION через LLM
# ──────────────────────────────────────────────

def formal_verification(image_path: str,
                         client: genai.Client,
                         checker_report: str = "") -> str:
    """
    Передаём фото + отчёт формальной проверки (sympy/Wolfram) в LLM.
    LLM читает решение с фото и проводит FORMAL VERIFICATION,
    опираясь на эталонные корни и результаты проверки шагов.
    """
    path = Path(image_path)
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",  ".webp": "image/webp",
    }
    mime_type = mime_map.get(path.suffix.lower(), "image/jpeg")

    print("  Загружаю фото для верификации...")
    my_file = client.files.upload(file=str(path))

    user_text = "Проведи FORMAL VERIFICATION этого решения согласно инструкции."
    if checker_report:
        user_text += f"\n\n{checker_report}"

    response = client.models.generate_content(
        model=GEMMA_MODEL,
        contents=[
            my_file,
            user_text,
        ],
        config=types.GenerateContentConfig(
            system_instruction=FORMAL_VERIFICATION_PROMPT,
            thinking_config=types.ThinkingConfig(
                thinking_level="high"
            )
        ),
    )
    return response.text.strip()


# ──────────────────────────────────────────────
# Вывод шагов
# ──────────────────────────────────────────────

def print_steps(steps: list):
    for i, step in enumerate(steps):
        t    = step.get("type", "?")
        lat  = step.get("latex", "")
        comm = step.get("comment", "")
        print(f"    [{i}] {t:16s} | {lat}")
        if comm:
            print(f"         {'':16s} | // {comm}")


def print_step_results(step_results: list):
    for entry in step_results:
        idx     = entry["index"]
        stype   = entry["type"]
        latex   = entry["latex"]
        checked = entry["checked"]
        ok      = entry["ok"]
        reason  = entry["reason"]

        if checked and ok is True:
            status = "✓"
        elif checked and ok is False:
            status = "✗"
        else:
            status = "⚠"

        print(f"    [{idx}] {status} [{stype:16s}] {latex}")
        if not (checked and ok is True):
            print(f"           {'':20s} → {reason}")


# ──────────────────────────────────────────────
# Основной пайплайн
# ──────────────────────────────────────────────

def run_pipeline(image_path: str,
                 equation_override: str = None) -> dict:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("Установи GOOGLE_API_KEY:\n  export GOOGLE_API_KEY='твой_ключ'")

    client = genai.Client(api_key=api_key)

    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  Фото: {image_path}")
    print(sep)

    # 1. OCR
    print("\n[1/3] OCR — извлечение типизированных шагов из фото...")
    ocr_result = ocr_image(image_path, client)

    equation = equation_override or ocr_result.get("equation", "")
    steps    = ocr_result.get("steps", [])
    answer   = ocr_result.get("answer", "")

    print(f"  Уравнение : {equation}")
    print(f"  Шагов     : {len(steps)}")
    print_steps(steps)
    print(f"  Ответ     : {answer}")

    # 2. Checker: sympy проверяет шаги, эталонные корни — sympy или Wolfram
    print("\n[2/3] Checker — sympy шаги + Wolfram эталонные корни...")
    result = check_solution(equation, steps, answer, use_wolfram=True)

    print(f"  Solver    : {result['solver_method']}")
    print(f"  Корни     : {result['correct_roots']}")
    print(f"  Needs LLM : {result['needs_llm']}")
    print(f"  Шаги:")
    print_step_results(result["step_results"])
    if result["answer_check"]:
        ac = result["answer_check"]
        print(f"  Ответ     : {'✓ верный' if ac['is_correct'] else '✗ неверный'}")

    # 3. Formal Verification — Gemma получает фото + отчёт формальной проверки.
    #    Пропускаем LLM только когда чекер уверенно ставит 1
    #    (precision таких единиц ~0.98).
    verification = None
    if result["score"] == 1:
        print(f"\n[3/3] Чекер уверенно ставит 1 — LLM не нужен.")
        print(f"  Итоговый балл: 1 / 1")
    else:
        report = build_checker_report(result, equation, answer)
        print("\n[3/3] FORMAL VERIFICATION — фото + отчёт чекера передаём в LLM...")
        verification = formal_verification(image_path, client, checker_report=report)
        print(f"\n{'─'*60}")
        print(verification)
        print(f"{'─'*60}\n")

    return {
        "ocr":          ocr_result,
        "equation":     equation,
        "checker":      result,
        "verification": verification,
    }


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ЕГЭ чекер: фото → OCR → sympy → FORMAL VERIFICATION"
    )
    parser.add_argument("image", help="Путь к фото (jpg/png/webp)")
    parser.add_argument("--equation", "-e", default=None,
                        help="Исходное уравнение в LaTeX (переопределяет OCR)")
    parser.add_argument("--json", action="store_true",
                        help="Вывести полный результат в JSON")

    args = parser.parse_args()

    output = run_pipeline(
        image_path=args.image,
        equation_override=args.equation,
    )

    if args.json:
        checker = output["checker"]
        if checker.get("correct_roots"):
            checker["correct_roots"] = [float(r) for r in checker["correct_roots"]]
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
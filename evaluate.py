
import re
import csv
import sys
import json
import time
from pathlib import Path

import pandas as pd
from sklearn.metrics import f1_score

from pipeline import run_pipeline

GOLDEN_SET_DIR = Path("golden set")
IMAGES_DIR     = GOLDEN_SET_DIR / "images"
GT_CSV         = GOLDEN_SET_DIR / "set.csv"
OUTPUT_CSV     = Path("results.csv")


# ──────────────────────────────────────────────
# Ground truth
# ──────────────────────────────────────────────

def load_ground_truth(csv_path: Path) -> dict:
    """image_stem → {'score': int, 'comment': str, 'type of equation': str}"""
    gt = {}
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            name = Path(row['image']).stem if '.' in row['image'] else row['image']
            gt[name] = {
                'score':            int(row['score']) if row['score'].strip() else '',
                'type of equation': row.get('type of equation', ''),
                'comment':          row.get('comment', ''),
            }
    return gt


# ──────────────────────────────────────────────
# Score extraction from LLM text
# ──────────────────────────────────────────────

def extract_score_from_verification(text: str) -> int | None:
    """Парсит '0' или '1' из текста FORMAL VERIFICATION."""
    if not text:
        return None

    # Сохраняем тексты для отладки
    with open("verif_debug.txt", "a", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write(text[:500] + "\n")

    patterns = [
        # "Итоговый балл: 1" / "**Итоговый балл:** 1" / "**Итоговый балл**\n0"
        # Разрешаем любые символы между "балл" и цифрой, включая перенос строки
        r'итоговый\s+балл[^01]{0,25}([01])\b',
        r'итоговый\s+балл[^01\n]{0,20}([01])\b',
        # "**1 балл**" / "1 балл" / "0 баллов"
        r'\*?\*?([01])\*?\*?\s+балл',
        # "балл: 1" / "балл — 0" / "балл:** 1"
        r'балл[^01\n]{0,10}([01])\b',
        # "score: 1"
        r'score[^01\n]{0,10}([01])\b',
        # "оценка: 1"
        r'оценка[^01\n]{0,10}([01])\b',
        # "1/1" / "0/1"
        r'\b([01])/1\b',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return int(m.group(1))
    return None


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    # Диапазон из аргументов командной строки (1-based включительно)
    start_n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    end_n   = int(sys.argv[2]) if len(sys.argv) > 2 else 200

    gt = load_ground_truth(GT_CSV)

    all_images = sorted(IMAGES_DIR.glob("*.png"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0)
    images = all_images[start_n - 1 : end_n]
    print(f"Найдено изображений: {len(all_images)}, обрабатываем: {len(images)} (#{start_n}–#{end_n})")

    # Если файл результатов уже есть — дописываем, иначе создаём новый
    existing_df = None
    if OUTPUT_CSV.exists() and start_n > 1:
        existing_df = pd.read_csv(OUTPUT_CSV, encoding='utf-8-sig')
        # Убираем строки-метрики если они есть
        existing_df = existing_df[~existing_df['image'].astype(str).str.startswith('---')]

    rows = []

    for i, img_path in enumerate(images, 1):
        name = img_path.stem
        print(f"\n[{i}/{len(images)}] {img_path.name}")

        row = {
            'image':            img_path.name,
            'latex_ocr':        '',
            'equation':         '',
            'answer':           '',
            'method':           'error',
            'predicted_score':  -1,
            'ground_truth':     gt.get(name, {}).get('score', ''),
            'match':            None,
            'type_of_equation': gt.get(name, {}).get('type of equation', ''),
            'gt_comment':       gt.get(name, {}).get('comment', ''),
            'sympy_errors':     '',
            'llm_comment':      '',
        }

        try:
            output = run_pipeline(str(img_path))

            ocr     = output.get('ocr', {})
            checker = output.get('checker', {})
            verif   = output.get('verification')

            row['latex_ocr'] = json.dumps(ocr.get('steps', []), ensure_ascii=False)
            row['equation']  = output.get('equation', '')
            row['answer']    = ocr.get('answer', '')
            row['method']    = checker.get('solver_method', 'error')

            # Определяем predicted_score: если LLM вызывалась — её вердикт финальный,
            # иначе — уверенная единица чекера
            if verif:
                predicted = extract_score_from_verification(verif)
            else:
                predicted = checker.get('score')

            row['predicted_score'] = predicted if predicted is not None else -1

            # Ошибки sympy
            step_results = checker.get('step_results', [])
            errors = [f"[{s['type']}] {s['reason']}" for s in step_results if s.get('ok') is False]
            row['sympy_errors'] = '; '.join(errors)

            # Полный текст LLM верификации
            row['llm_comment'] = verif or ''

            # Совпадение с GT
            if isinstance(row['ground_truth'], int) and row['predicted_score'] != -1:
                row['match'] = int(row['ground_truth'] == row['predicted_score'])

        except Exception as e:
            print(f"  ОШИБКА: {e}")
            row['sympy_errors'] = str(e)

        rows.append(row)

        # Сохраняем после каждого изображения (crash-safe), объединяя с предыдущими
        df_new = pd.DataFrame(rows)
        df_save = pd.concat([existing_df, df_new], ignore_index=True) if existing_df is not None else df_new
        df_save.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')

    # ──────────────────────────────────────────────
    # F1 — считаем по всем данным в файле
    # ──────────────────────────────────────────────

    df_all = pd.concat([existing_df, pd.DataFrame(rows)], ignore_index=True) if existing_df is not None else pd.DataFrame(rows)
    valid = df_all[(df_all['ground_truth'] != '') & (df_all['predicted_score'] != -1)].copy()
    valid['ground_truth']    = valid['ground_truth'].astype(int)
    valid['predicted_score'] = valid['predicted_score'].astype(int)

    if len(valid) == 0:
        print("\nНет валидных строк для F1.")
    else:
        f1 = f1_score(valid['ground_truth'], valid['predicted_score'], zero_division=0)
        acc = (valid['ground_truth'] == valid['predicted_score']).mean()
        print(f"\n{'='*50}")
        print(f"  Всего изображений   : {len(df_all)}")
        print(f"  Валидных (для F1)   : {len(valid)}")
        print(f"  Accuracy            : {acc:.3f}")
        print(f"  F1 (binary)         : {f1:.3f}")
        print(f"{'='*50}")

        # Дописываем итог в конец CSV
        n_cols = len(df_all.columns)
        df_all.loc[len(df_all)] = ['--- METRICS ---'] + [''] * (n_cols - 1)
        df_all.loc[len(df_all)] = [f'F1={f1:.4f}  Acc={acc:.4f}  N={len(valid)}'] + [''] * (n_cols - 1)
        df_all.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')

    print(f"\nРезультаты сохранены в {OUTPUT_CSV}")


if __name__ == "__main__":
    main()

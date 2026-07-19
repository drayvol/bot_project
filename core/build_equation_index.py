"""
Векторная база уравнений №13 в Qdrant.

Источник: data/equations_task13.jsonl — задачи №13 с решениями.
Пайплайн:
  1. Уравнение (LaTeX) → TF-IDF (символьные n-граммы) → TruncatedSVD → L2-норма.
  2. Qdrant (сервис из QDRANT_URL, либо embedded ./qdrant_db), payload: уравнение, решение, ответ,
     категория, url, аналоги.
  3. Векторизатор → equation_vectorizer.joblib (им же кодируются запросы).

Запуск:  python -m core.build_equation_index
"""

import os
import re
import json
import uuid
import warnings
warnings.filterwarnings('ignore')

import joblib
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import Normalizer

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

SOURCE          = 'data/equations_task13.jsonl'
GOLDEN_SET      = ''  # golden set не входит в комплект бота  # + уравнения gt=1
QDRANT_PATH     = 'qdrant_db'
COLLECTION      = 'equations'
VECTORIZER_PATH = 'models/equation_vectorizer.joblib'
DIM             = 128


def normalize_equation(eq: str) -> str:
    """Нормализация LaTeX перед векторизацией."""
    s = str(eq).strip()
    s = re.sub(r'\\left|\\right', '', s)
    s = re.sub(r'\s+', '', s)
    return s


def load_golden() -> list:
    """Уравнения golden set с верными решениями (gt=1) в формате записей базы."""
    import pandas as pd
    df = pd.read_csv(GOLDEN_SET, encoding='utf-8-sig')
    df = df[~df['image'].astype(str).str.startswith('---')]
    df = df[df['ground_truth'].notna()]
    df = df[df['ground_truth'].astype(int) == 1]
    recs = []
    for _, r in df.iterrows():
        eq = str(r.get('equation', '') or '')
        if not eq or eq == 'nan':
            continue
        # шаги решения из latex_ocr → читаемый текст
        solution = ''
        try:
            steps = json.loads(r['latex_ocr'])
            solution = ' '.join(f"${s.get('latex','')}$" for s in steps)
        except Exception:
            pass
        recs.append({
            'id':        f"golden_{r['image']}",
            'url':       '',
            'equation':  eq,
            'condition': f'Решите уравнение ${eq}$',
            'solution':  solution,
            'answer':    str(r.get('answer', '') or ''),
            'category':  str(r.get('type_of_equation', '') or 'golden set'),
            'analogs':   [],
        })
    return recs


def main():
    recs = [json.loads(l) for l in open(SOURCE, encoding='utf-8')]
    golden = load_golden() if GOLDEN_SET else []
    print(f'база: {len(recs)}, golden set (gt=1): {len(golden)}')
    recs = recs + golden

    # дедупликация по нормализованному уравнению (базовые записи в приоритете)
    seen, data = set(), []
    for r in recs:
        norm = normalize_equation(r['equation'])
        if not norm or norm in seen:
            continue
        seen.add(norm)
        r['norm'] = norm
        data.append(r)
    print(f'Задач: {len(recs)} → {len(data)} уникальных уравнений')

    vectorizer = Pipeline([
        ('tfidf', TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 5),
                                  lowercase=False)),
        ('svd', TruncatedSVD(n_components=DIM, random_state=42)),
        ('norm', Normalizer()),
    ])
    vectors = vectorizer.fit_transform([r['norm'] for r in data])
    joblib.dump(vectorizer, VECTORIZER_PATH)
    print(f'Векторы: {vectors.shape} → {VECTORIZER_PATH}')

    _url = os.environ.get('QDRANT_URL')
    client = QdrantClient(url=_url) if _url else QdrantClient(path=QDRANT_PATH)
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
    )

    points = [
        PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, r['norm'])),
            vector=vectors[i].tolist(),
            payload={
                'problem_id': r['id'],
                'equation':   r['equation'],
                'condition':  r['condition'],
                'solution':   r['solution'],
                'answer':     r['answer'],
                'category':   r['category'],
                'analogs':    r['analogs'],
            },
        )
        for i, r in enumerate(data)
    ]
    client.upsert(collection_name=COLLECTION, points=points)
    print(f'Готово: {client.count(COLLECTION).count} точек в "{COLLECTION}" ({QDRANT_PATH})')


if __name__ == '__main__':
    main()

"""
search_equations.py — поиск похожих уравнений по косинусной близости.

Использование:
  python search_equations.py '2\\cos^2 x + 3\\sin x - 3 = 0'
  python search_equations.py '...' --top 10

Или из кода:
  from search_equations import search
  hits = search(r'2\\cos^2 x + 3\\sin x - 3 = 0', top_k=5)
"""

import os
import sys
import warnings
warnings.filterwarnings('ignore')

import joblib
from qdrant_client import QdrantClient

from build_equation_index import normalize_equation, QDRANT_PATH, COLLECTION, VECTORIZER_PATH

_vectorizer = None
_client = None


def _load():
    global _vectorizer, _client
    if _vectorizer is None:
        _vectorizer = joblib.load(VECTORIZER_PATH)
    if _client is None:
        # QDRANT_URL задан → отдельный сервис (нужно для нескольких воркеров),
        # иначе embedded (однопроцессный режим)
        url = os.environ.get('QDRANT_URL')
        _client = QdrantClient(url=url) if url else QdrantClient(path=QDRANT_PATH)
    return _vectorizer, _client


def search(equation_latex: str, top_k: int = 5) -> list:
    """→ [{'score', 'equation', 'category', 'solution', 'answer', 'url', ...}]."""
    vec, cli = _load()
    q = vec.transform([normalize_equation(equation_latex)])[0].tolist()
    hits = cli.query_points(collection_name=COLLECTION, query=q, limit=top_k).points
    return [{'score': round(h.score, 4), **h.payload} for h in hits]


if __name__ == '__main__':
    query = sys.argv[1] if len(sys.argv) > 1 else r'2\cos^2 x + 3\sin x - 3 = 0'
    top = int(sys.argv[sys.argv.index('--top') + 1]) if '--top' in sys.argv else 5
    print(f'Запрос: {query}\n')
    for h in search(query, top):
        print(f"  {h['score']:.4f}  [{h['category'][:32]:32s}]  {h['equation'][:60]}")
        print(f"           ответ: {h['answer'][:70]}")

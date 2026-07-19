"""Накопление присланных пользователями уравнений в векторной базе.

Отдельная коллекция `user_equations` в том же embedded Qdrant: не смешиваем
со справочной базой, чтобы студенческие решения не попадали в выдачу
«похожих задач», но база уравнений растёт с каждой проверкой.

Дедупликация: ищем ближайшие в обеих коллекциях и сравниваем
normalize_equation() на точное совпадение. Повторная оценка той же заявки
(после правки OCR) обновляет свою же точку — id детерминирован от submission_id.
"""

import datetime
import uuid

from qdrant_client.models import Distance, PointStruct, VectorParams

from core.build_equation_index import COLLECTION, normalize_equation
from core.search_equations import _load

USER_COLLECTION = 'user_equations'
_DEDUP_TOP_K = 3


def _point_id(submission_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'submission:{submission_id}'))


def _ensure_collection(cli, size: int):
    if not cli.collection_exists(USER_COLLECTION):
        cli.create_collection(
            USER_COLLECTION,
            vectors_config=VectorParams(size=size, distance=Distance.COSINE))


def _find_same(cli, collection: str, query: list, normalized: str) -> dict | None:
    """Ближайшие соседи → payload первого с точно таким же уравнением."""
    hits = cli.query_points(collection_name=collection, query=query,
                            limit=_DEDUP_TOP_K).points
    for h in hits:
        if normalize_equation(h.payload.get('equation', '')) == normalized:
            return h.payload
    return None


def add_user_equation(equation_latex: str, submission_id: str,
                      payload_extra: dict = None) -> str:
    """Кладёт уравнение в user_equations, если такого ещё нет.

    → 'added' | 'updated' (повторная оценка той же заявки)
      | 'duplicate_base' | 'duplicate_user' | 'skipped_empty'
    """
    equation_latex = (equation_latex or '').strip()
    if not equation_latex:
        return 'skipped_empty'

    vec, cli = _load()
    normalized = normalize_equation(equation_latex)
    query = vec.transform([normalized])[0].tolist()
    _ensure_collection(cli, len(query))

    if _find_same(cli, COLLECTION, query, normalized) is not None:
        return 'duplicate_base'

    same_user = _find_same(cli, USER_COLLECTION, query, normalized)
    if same_user is not None and same_user.get('submission_id') != submission_id:
        return 'duplicate_user'

    payload = {
        'equation': equation_latex,
        'source': 'user',
        'submission_id': submission_id,
        'added_at': datetime.date.today().isoformat(),
        **(payload_extra or {}),
    }
    cli.upsert(USER_COLLECTION, [
        PointStruct(id=_point_id(submission_id), vector=query, payload=payload)])
    return 'updated' if same_user is not None else 'added'

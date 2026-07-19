"""Накопление пользовательских уравнений: дедуп и обновление (Qdrant in-memory)."""

import os

import joblib
import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

import core.user_equations as ue
from core.build_equation_index import COLLECTION, normalize_equation

BASE_EQ = r'2\cos^2 x + 3\sin x - 3 = 0'
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def qmem(monkeypatch):
    vec = joblib.load(os.path.join(PROJECT_ROOT, 'models/equation_vectorizer.joblib'))
    cli = QdrantClient(':memory:')
    v = vec.transform([normalize_equation(BASE_EQ)])[0].tolist()
    cli.create_collection(COLLECTION, vectors_config=VectorParams(
        size=len(v), distance=Distance.COSINE))
    cli.upsert(COLLECTION, [PointStruct(id=1, vector=v, payload={'equation': BASE_EQ})])
    monkeypatch.setattr(ue, '_load', lambda: (vec, cli))
    return cli


def test_duplicate_of_base(qmem):
    assert ue.add_user_equation(BASE_EQ, 'sub_a') == 'duplicate_base'


def test_add_then_dedup_then_update(qmem):
    new_eq = r'\sin 7x \cdot \cos 5x = \frac{17}{31}'
    assert ue.add_user_equation(new_eq, 'sub_b') == 'added'
    assert ue.add_user_equation(new_eq, 'sub_c') == 'duplicate_user'
    assert ue.add_user_equation(new_eq, 'sub_b') == 'updated'
    assert qmem.count(ue.USER_COLLECTION).count == 1


def test_payload_stored(qmem):
    eq = r'\log_2 (x+1) = 3'
    ue.add_user_equation(eq, 'sub_d', {'score': 1, 'suspicious_ocr': False})
    point = qmem.scroll(ue.USER_COLLECTION, limit=10)[0][0]
    assert point.payload['equation'] == eq
    assert point.payload['score'] == 1
    assert point.payload['source'] == 'user'


def test_empty_skipped(qmem):
    assert ue.add_user_equation('   ', 'sub_e') == 'skipped_empty'

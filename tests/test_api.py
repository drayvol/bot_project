"""REST API: жизненный цикл заявки без очереди и воркера (enqueue замокан)."""

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from bot import db

OCR = {'equation': r'\sin x = 1',
       'steps': [{'type': '', 'latex': r'x = \frac{\pi}{2} + 2\pi k', 'comment': ''}],
       'answer': r'\frac{\pi}{2} + 2\pi k'}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api_main, 'enqueue', lambda *a: 1)
    with TestClient(api_main.app) as c:
        yield c


def _submit(client) -> str:
    resp = client.post('/submissions',
                       files={'photo': ('sol.jpg', b'\xff\xd8fake', 'image/jpeg')})
    assert resp.status_code == 201
    return resp.json()['id']


def test_health(client):
    assert client.get('/health').json() == {'status': 'ok'}


def test_create_and_poll(client):
    sub_id = _submit(client)
    got = client.get(f'/submissions/{sub_id}').json()
    assert got['status'] == 'new' and got['ocr'] is None
    assert got['rating'] is None


def test_wrong_content_type(client):
    resp = client.post('/submissions',
                       files={'photo': ('x.pdf', b'%PDF', 'application/pdf')})
    assert resp.status_code == 415


def test_confirm_before_ocr_is_409(client):
    sub_id = _submit(client)
    assert client.post(f'/submissions/{sub_id}/confirm').status_code == 409


def test_full_lifecycle(client):
    sub_id = _submit(client)
    # воркер «распознал»
    db.update_submission(sub_id, ocr=OCR, ocr_original=OCR, status='awaiting_confirm')

    patched = client.patch(f'/submissions/{sub_id}/ocr',
                           json={'equation': r'\cos x = 0'}).json()
    assert patched['ocr']['equation'] == r'\cos x = 0'
    assert patched['ocr_original']['equation'] == OCR['equation']
    assert patched['status'] == 'editing'

    confirmed = client.post(f'/submissions/{sub_id}/confirm').json()
    assert confirmed['status'] == 'grading'

    assert client.post(f'/submissions/{sub_id}/rating',
                       json={'rating': 1}).status_code == 200
    assert client.get(f'/submissions/{sub_id}').json()['rating'] == 1


def test_patch_steps_as_strings(client):
    sub_id = _submit(client)
    db.update_submission(sub_id, ocr=OCR, ocr_original=OCR, status='awaiting_confirm')
    got = client.patch(f'/submissions/{sub_id}/ocr',
                       json={'steps': ['x = 1', 'x = 2']}).json()
    assert got['ocr']['steps'][0] == {'type': '', 'latex': 'x = 1',
                                      'comment': 'правка пользователя'}


def test_404(client):
    assert client.get('/submissions/nope').status_code == 404
    assert client.post('/submissions/nope/confirm').status_code == 404

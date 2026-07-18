"""SQLite-хранилище заявок."""

from bot import db


def setup_module():
    db.init_db()


def test_create_and_get():
    sid = db.create_submission(100, 200, '/data/photos/x.jpg')
    sub = db.get_submission(sid)
    assert sub['chat_id'] == 100 and sub['user_id'] == 200
    assert sub['status'] == 'new'
    assert sub['ocr'] is None and sub['result'] is None


def test_json_roundtrip_and_status():
    sid = db.create_submission(1, 2, 'p.jpg')
    ocr = {'equation': r'\sin x = 1', 'steps': [{'latex': 'x', 'type': '', 'comment': ''}],
           'answer': 'π/2'}
    db.update_submission(sid, ocr=ocr, ocr_original=ocr, status='awaiting_confirm')
    sub = db.get_submission(sid)
    assert sub['ocr'] == ocr and sub['ocr_original'] == ocr
    assert sub['status'] == 'awaiting_confirm'


def test_edits_keep_original():
    sid = db.create_submission(1, 2, 'p.jpg')
    db.update_submission(sid, ocr={'equation': 'до'}, ocr_original={'equation': 'до'})
    db.update_submission(sid, ocr={'equation': 'после'})
    sub = db.get_submission(sid)
    assert sub['ocr']['equation'] == 'после'
    assert sub['ocr_original']['equation'] == 'до'


def test_rating():
    sid = db.create_submission(1, 2, 'p.jpg')
    db.update_submission(sid, rating=0)
    assert db.get_submission(sid)['rating'] == 0
    db.update_submission(sid, rating=1)
    assert db.get_submission(sid)['rating'] == 1


def test_missing_submission():
    assert db.get_submission('нет такой') is None

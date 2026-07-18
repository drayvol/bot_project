"""apply_edits: парсер построчных правок OCR."""

from bot.ocr_edit import apply_edits


def _ocr():
    return {
        'equation': r'\sin x = 1',
        'steps': [
            {'type': 'замена', 'latex': r'\sin x = t', 'comment': 'замена'},
            {'type': 'уравнение', 'latex': 't = 1', 'comment': 'корень'},
        ],
        'answer': r'\frac{\pi}{2}',
    }


def test_replace_equation_and_answer():
    new, applied, rejected = apply_edits(_ocr(), 'У: \\cos x = 0\nО: \\pi k')
    assert new['equation'] == r'\cos x = 0'
    assert new['answer'] == r'\pi k'
    assert applied == ['уравнение', 'ответ'] and not rejected


def test_replace_step_keeps_dict_structure():
    new, applied, _ = apply_edits(_ocr(), '2: t = -1')
    assert new['steps'][1]['latex'] == 't = -1'
    assert new['steps'][1]['type'] == 'уравнение'
    assert new['steps'][1]['comment'] == 'правка пользователя'
    assert applied == ['шаг 2']


def test_delete_and_append_step():
    new, applied, _ = apply_edits(_ocr(), '1: -\n+: x = 5')
    assert len(new['steps']) == 2
    assert new['steps'][0]['latex'] == 't = 1'
    assert new['steps'][1] == {'type': '', 'latex': 'x = 5',
                               'comment': 'добавлено пользователем'}


def test_out_of_range_and_garbage_rejected():
    new, applied, rejected = apply_edits(_ocr(), '9: x = 1\nпросто текст')
    assert not applied
    assert rejected == ['9: x = 1', 'просто текст']


def test_original_not_mutated():
    ocr = _ocr()
    apply_edits(ocr, 'У: y = 0\n1: -')
    assert ocr['equation'] == r'\sin x = 1'
    assert len(ocr['steps']) == 2

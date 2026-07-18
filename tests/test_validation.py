"""reject_reason: отсев фото без решения уравнения."""

from bot.validation import reject_reason


def _good_ocr():
    return {'equation': r'\sin x = 1',
            'steps': [{'type': 't', 'latex': 'x = \\pi/2', 'comment': ''}],
            'answer': r'\frac{\pi}{2} + 2\pi k'}


def test_good_solution_passes():
    assert reject_reason(_good_ocr()) is None


def test_not_math_flag():
    reason = reject_reason({'not_math': True, 'reason': 'фотография кота',
                            'equation': '', 'steps': [], 'answer': ''})
    assert reason is not None and 'кота' in reason


def test_empty_equation():
    assert reject_reason({'equation': '', 'steps': [], 'answer': ''}) is not None


def test_no_equals_sign():
    ocr = _good_ocr()
    ocr['equation'] = r'просто \sin x'
    assert reject_reason(ocr) is not None


def test_condition_only_no_steps_no_answer():
    assert reject_reason({'equation': 'x = 1', 'steps': [], 'answer': ''}) is not None


def test_answer_without_steps_ok():
    # решение «в уме»: уравнение + ответ без выкладок — пропускаем на оценку
    assert reject_reason({'equation': r'\sin x = 0', 'steps': [],
                          'answer': r'\pi k'}) is None

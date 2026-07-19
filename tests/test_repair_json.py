"""_repair_json: починка типовых поломок JSON от Gemma."""

import json

from core.pipeline import _repair_json


def test_valid_json_untouched():
    raw = r'{"equation": "x=1", "steps": [{"type": "t", "latex": "\\sin x", "comment": "c"}], "answer": "1"}'
    parsed = json.loads(_repair_json(raw))
    assert parsed['steps'][0]['latex'] == r'\sin x'


def test_space_instead_of_colon():
    raw = r'{"equation "x=1", "steps": [], "answer": "1"}'
    assert json.loads(_repair_json(raw))['equation'] == 'x=1'


def test_colon_inside_key_quotes():
    raw = r'{"equation": "x=1", "steps": [{"type": "t", "latex: "-\\sqrt{3} \\notin [-1; 1]", "comment": "c"}], "answer": "1"}'
    parsed = json.loads(_repair_json(raw))
    assert parsed['steps'][0]['latex'] == r'-\sqrt{3} \notin [-1; 1]'


def test_single_backslash_latex_commands_doubled():
    raw = r'{"equation": "\cos 2x = 1", "steps": [], "answer": "\pi k"}'
    parsed = json.loads(_repair_json(raw))
    assert parsed['equation'] == r'\cos 2x = 1'
    assert parsed['answer'] == r'\pi k'

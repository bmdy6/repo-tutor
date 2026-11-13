from pathlib import Path

from repo_tutor.scanner import scan
from repo_tutor.verify import verify

FIXTURE = Path(__file__).parent / 'fixtures/sample'


def test_valid_symbol_citation_and_missing_coverage():
    inv = scan(FIXTURE)
    lesson = '# Lesson\n\n- Normalizes input [clean](src/demo/util.py:2).\n\n```mermaid\nflowchart TD\n a[clean]\n```\n'
    report = verify(FIXTURE, inv, {'01.md': lesson})
    assert report['citations']['invalid'] == []
    assert report['coverage']['covered'] == 1
    assert report['coverage']['missing']
    assert report['human_review_required'] is True
    assert report['passed'] is False


def test_wrong_symbol_range_escape_and_unknown_citation():
    inv = scan(FIXTURE)
    lesson = '''- Wrong [Service](src/demo/util.py:2).
- Wrong [clean](src/demo/util.py:900).
- Escape [clean](../outside.py:1).
- Missing [clean](missing.py:1).
- Bare src/demo/util.py:2
'''
    report = verify(FIXTURE, inv, {'01.md': lesson})
    assert len(report['citations']['invalid']) == 5
    assert report['coverage']['covered'] == 0


def test_inventory_only_and_uncited_prose_do_not_prove_coverage():
    inv = scan(FIXTURE)
    report = verify(FIXTURE, inv, {'outline.md': '[clean](src/demo/util.py:2)'})
    assert report['coverage']['covered'] == 0
    report = verify(FIXTURE, inv, {'01.md': 'The system persists every request to disk.\n'})
    assert report['lesson_issues']


def test_source_drift(tmp_path):
    file = tmp_path / 'm.py'
    file.write_text('def hello():\n    return 1\n')
    inv = scan(tmp_path)
    file.write_text('def hello():\n    return 2\n')
    report = verify(tmp_path, inv, {'01.md': '- Returns one [hello](m.py:1).\n'})
    assert report['source_drift'] == ['m.py']

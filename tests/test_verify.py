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


def test_graph_nodes_and_endpoints_must_exist_in_inventory():
    from repo_tutor.diagrams import diagram_id, render_diagram
    inv = scan(FIXTURE)
    node = next(n for n in inv['nodes'] if n['name'] == 'clean')
    chart = render_diagram(inv, [node['id']])
    assert not any('diagram' in i['reason'] for i in verify(FIXTURE, inv, {'01.md': chart})['lesson_issues'])
    bad = chart.replace('demo.util.clean', 'demo.util.nonexistent')
    report = verify(FIXTURE, inv, {'01.md': bad})
    assert any('diagram node' in i['reason'] for i in report['lesson_issues'])
    undeclared = chart.replace('\n```', f'\n  {diagram_id(node["id"])} -->|call| n0000000000000000\n```')
    report = verify(FIXTURE, inv, {'01.md': undeclared})
    assert any('endpoint' in i['reason'] for i in report['lesson_issues'])
    for chart in ('```mermaid\nflowchart TD\n```\n', '```mermaid\nflowchart TD\n fake[Invented]\n```\n'):
        assert any('diagram' in i['reason'] for i in verify(FIXTURE, inv, {'01.md': chart})['lesson_issues'])


def test_prose_and_reference_only_coverage_are_disjoint():
    inv = scan(FIXTURE)
    lesson = '''## 学习目标
- 学会追踪源码 [clean](src/demo/util.py:2)
## 按调用顺序理解
从归一化输入开始阅读。 [clean](src/demo/util.py:2)
## 关键符号速查
| 符号 | 类型 | 出处 |
| --- | --- | --- |
| Service | class | [Service](src/demo/core.py:3) |
## 自测题
1. 入口？ [hello](src/demo/web.py:4)
答案：见源码。 [hello](src/demo/web.py:4)
## 下一课
继续。 [cli](src/demo/web.py:8)
'''
    report = verify(FIXTURE, inv, {'01.md': lesson})
    coverage = report['coverage']
    assert coverage['narrative'] == 1
    assert coverage['reference_only'] == 1
    assert coverage['other_only'] == 2
    assert coverage['narrative'] + coverage['reference_only'] + coverage['other_only'] == coverage['covered']


def test_empty_course_and_missing_sections_fail_even_with_valid_diagram(tmp_path):
    from repo_tutor.diagrams import render_diagram
    (tmp_path / 'm.py').write_text('def hello(): return 1\n')
    inv = scan(tmp_path)
    chart = render_diagram(inv, [inv['nodes'][1]['id']])
    report = verify(tmp_path, inv, {'01.md': '[hello](m.py:1)\n' + chart + '\n'})
    assert report['coverage']['covered'] == 1
    assert not report['passed']
    assert any('section' in i['reason'] for i in report['lesson_issues'])


def test_unclosed_extra_chart_and_missing_flowchart_header_are_rejected():
    from repo_tutor.diagrams import diagram_issues, render_diagram
    inv = scan(FIXTURE)
    chart = render_diagram(inv, [inv['nodes'][0]['id']])
    assert diagram_issues(chart, inv) == []
    assert diagram_issues(chart + '\n```mermaid\nflowchart TD\n fake[ghost]', inv)
    assert diagram_issues(chart.replace('flowchart TD\n', ''), inv)

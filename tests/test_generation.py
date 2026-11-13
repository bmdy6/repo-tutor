import json
from pathlib import Path

import pytest

from repo_tutor.config import Config
from repo_tutor.course import make_plan, render_outline, write_lesson
from repo_tutor.model import ModelClient
from repo_tutor.scanner import scan
from repo_tutor.verify import verify

FIXTURE = Path(__file__).parent / 'fixtures/sample'

class FakeModel:
    def __init__(self):
        self.calls = 0
    def complete(self, prompt):
        self.calls += 1
        data = json.loads(prompt)
        if data['task'] == 'outline':
            return {'titles': [{'id': x['id'], 'title': '基础与入口'} for x in data['lessons']]}
        ids = [x['id'] for x in data['evidence'][:2]]
        sections = ['system', 'entries', 'modules', 'lifecycle'] if data['kind'] == 'overview' else ['flow'] * 3
        return {'goals': ['理解入口与职责', '沿源码追踪一次调用'],
                'paragraphs': [{'section': section, 'text': '先从入口理解职责，再沿已解析的调用关系阅读实现。',
                                'node_ids': ids} for section in sections],
                'quiz': [{'question': '这里从哪里开始阅读？', 'answer': '从提供的入口定义开始。',
                          'node_ids': ids} for _ in range(2)],
                'transition': '接着观察依赖这些基础的流程。'}



def test_fake_model_complete_course_and_budget_free_verification():
    inv = scan(FIXTURE)
    model = FakeModel()
    config = Config(nodes_per_lesson=3)
    plan = make_plan(inv, model, config)
    assert '# 课程大纲' in render_outline(inv, plan)
    lessons = {x['id'] + '.md': write_lesson(FIXTURE, inv, plan, x['id'], model, config)
               for x in plan['lessons']}
    report = verify(FIXTURE, inv, lessons)
    assert report['passed'], report
    assert model.calls == 1 + len(lessons)


def test_bad_model_output_rejected():
    class Bad:
        def complete(self, prompt):
            return {'titles': []}
    with pytest.raises(ValueError, match='titles'):
        make_plan(scan(FIXTURE), Bad(), Config())


def test_budget_counts_failures_and_persists(tmp_path):
    config = Config(api_key='unit-test-key', max_calls=1)
    def fail(*args, **kwargs):
        raise OSError('offline')
    client = ModelClient(config, tmp_path / 'usage.json', transport=fail)
    with pytest.raises(ValueError, match='request failed'):
        client.complete('{}')
    again = ModelClient(config, tmp_path / 'usage.json', transport=fail)
    with pytest.raises(ValueError, match='budget'):
        again.complete('{}')
    assert json.loads((tmp_path / 'usage.json').read_text())['attempts'] == 1


def test_evidence_size_failure_does_not_call_model():
    model = FakeModel()
    inv = scan(FIXTURE)
    plan = make_plan(inv, model, Config())
    with pytest.raises(ValueError, match='context'):
        write_lesson(FIXTURE, inv, plan, '01', model, Config(max_context_chars=1))
    assert model.calls == 1


def test_inline_code_is_valid_teaching_text_but_links_are_rejected():
    from repo_tutor.course import plain_text
    assert plain_text('通过 `dict[str, int]` 读取键。') == '通过 `dict[str, int]` 读取键。'
    with pytest.raises(ValueError):
        plain_text('Read [external](https://example.com)')


def test_overload_citations_cover_distinct_declarations(tmp_path):
    source = 'from typing import overload\n@overload\ndef convert(x: int): ...\n@overload\ndef convert(x: str): ...\ndef convert(x): return x\n'
    (tmp_path / 'm.py').write_text(source)
    lesson = '\n'.join(f'- Declaration [convert](m.py:{line}).' for line in (3, 5, 6))
    lesson += '\n```mermaid\nflowchart TD\n a[convert]\n```\n'
    report = verify(tmp_path, scan(tmp_path), {'01.md': lesson})
    assert report['coverage']['covered'] == 3
    assert report['citations']['invalid'] == []


def test_transport_request_and_ledger_never_store_key(tmp_path):
    import io
    captured = []
    def transport(request, **kwargs):
        captured.append(json.loads(request.data))
        return io.BytesIO(json.dumps({'model': 'local-test', 'choices': [
            {'finish_reason': 'stop', 'message': {'content': '{"facts": []}'}}],
            'usage': {'total_tokens': 4}}).encode())
    client = ModelClient(Config(api_key='unit-test-key'), tmp_path / 'usage.json', transport=transport)
    assert client.complete('{}') == {'facts': []}
    assert captured[0]['response_format'] == {'type': 'json_object'}
    text = (tmp_path / 'usage.json').read_text()
    assert 'unit-test-key' not in text
    assert json.loads(text)['requests'][0]['returned_model'] == 'local-test'


def test_non_object_outline_items_fail_cleanly():
    class Broken:
        def complete(self, prompt):
            return {'titles': ['not-an-object']}
    with pytest.raises(ValueError, match='titles'):
        make_plan(scan(FIXTURE), Broken(), Config())


def test_json_atomic_save_does_not_follow_predictable_temporary_symlink(tmp_path):
    from repo_tutor.model import save_json
    victim = tmp_path / 'keep.txt'
    victim.write_text('keep')
    (tmp_path / 'usage.tmp').symlink_to(victim)
    save_json(tmp_path / 'usage.json', {'attempts': 1})
    assert victim.read_text() == 'keep'


def test_course_is_connected_prose_with_overview_table_quiz_and_transition():
    inv = scan(FIXTURE)
    model = FakeModel()
    plan = make_plan(inv, model, Config())
    for item in plan['lessons']:
        text = write_lesson(FIXTURE, inv, plan, item['id'], model, Config())
        for heading in ('## 学习目标', '## 按调用顺序理解', '## 关键符号速查', '## 自测题', '## 下一课'):
            assert heading in text
        prose = text.split('## 按调用顺序理解')[1].split('## 关键符号速查')[0]
        assert not any(line.startswith('- **') for line in prose.splitlines())
        assert text.count('答案：') == 2
        assert '```mermaid' in text
        if item['kind'] == 'overview':
            for heading in ('### 系统做什么', '### 有哪些入口', '### 模块地图', '### 一次典型调用的生命周期'):
                assert heading in text
            assert '静态推断' in text


@pytest.mark.parametrize('field', ['goals', 'paragraphs', 'quiz', 'transition'])
def test_malformed_course_sections_rejected(field):
    class Bad(FakeModel):
        def complete(self, prompt):
            value = super().complete(prompt)
            if json.loads(prompt)['task'] == 'lesson':
                value[field] = []
            return value
    model = Bad()
    inv = scan(FIXTURE)
    plan = make_plan(inv, model, Config())
    with pytest.raises(ValueError):
        write_lesson(FIXTURE, inv, plan, '00', model, Config())


def test_model_cannot_cite_a_node_outside_evidence():
    class Invented(FakeModel):
        def complete(self, prompt):
            value = super().complete(prompt)
            if json.loads(prompt)['task'] == 'lesson':
                value['paragraphs'][0]['node_ids'] = ['invented.py::fake@1']
            return value
    model = Invented()
    inv = scan(FIXTURE)
    plan = make_plan(inv, model, Config())
    with pytest.raises(ValueError, match='evidence'):
        write_lesson(FIXTURE, inv, plan, '00', model, Config())


def test_source_drift_stops_generation_before_model_call(tmp_path):
    path = tmp_path / 'm.py'
    path.write_text('def start(): return 1\n')
    inv = scan(tmp_path)
    model = FakeModel()
    plan = make_plan(inv, model, Config())
    path.write_text('def start(): return 2\n')
    with pytest.raises(ValueError, match='source changed'):
        write_lesson(tmp_path, inv, plan, '00', model, Config())
    assert model.calls == 1


def test_no_entry_overview_explains_missing_lifecycle(tmp_path):
    (tmp_path / 'm.py').write_text('def library_api():\n    """Normalize a value for callers."""\n    return 1\n')
    inv = scan(tmp_path)
    model = FakeModel()
    plan = make_plan(inv, model, Config())
    assert plan['lessons'][0]['lifecycle'] is None
    text = write_lesson(tmp_path, inv, plan, '00', model, Config())
    assert '未识别入口' in text
    assert '无法推导入口生命周期' in text

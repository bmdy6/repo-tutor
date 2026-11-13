import copy
import json
from pathlib import Path

import pytest

from repo_tutor.config import Config
from repo_tutor.course import make_plan, validate_plan
from repo_tutor.scanner import scan

FIXTURE = Path(__file__).parent / 'fixtures/sample'


class NamingModel:
    def complete(self, prompt):
        data = json.loads(prompt)
        return {'titles': [{'id': x['id'], 'title': '功能课程'} for x in data['lessons']]}


def test_groups_are_module_owned_before_dependency_order():
    inv = scan(FIXTURE)
    plan = make_plan(inv, NamingModel(), Config(nodes_per_lesson=3))
    assert plan['schema_version'] == 2
    assert plan['lessons'][0]['id'] == '00'
    assert plan['lessons'][0]['kind'] == 'overview'
    nodes = {n['id']: n for n in inv['nodes']}
    groups = plan['lessons'][1:]
    assigned = [n for g in groups for n in g['node_ids']]
    assert len(assigned) == len(set(assigned))
    assert set(assigned) == {n['id'] for n in inv['nodes'] if n['public'] or n['entry']}
    assert all(len({nodes[i]['module'] for i in g['node_ids']}) == 1 or g['merged_cycle'] for g in groups)
    assert all(g['reading_order'] and set(g['reading_order']) <= nodes.keys() for g in groups)
    assert make_plan(inv, NamingModel(), Config(nodes_per_lesson=3)) == plan
    validate_plan(inv, plan)
    tampered = copy.deepcopy(plan)
    tampered['lessons'][1]['node_ids'].reverse()
    tampered['lessons'][1]['node_ids'].append(tampered['lessons'][2]['node_ids'][0])
    with pytest.raises(ValueError, match='group'):
        validate_plan(inv, tampered)


def test_protocol_and_constructor_entries_feed_distinct_flows(tmp_path):
    (tmp_path / 'web.py').write_text('''class Application:
    def __init__(self): self.configure()
    def configure(self): return 1
    def __call__(self, environ, start_response): return self.dispatch()
    def dispatch(self): return self.respond()
    def respond(self): return 2
''')
    inv = scan(tmp_path)
    nodes = {n['qualname']: n for n in inv['nodes']}
    assert 'constructor' in nodes['Application.__init__']['entry']
    assert 'protocol' in nodes['Application.__call__']['entry']
    plan = make_plan(inv, NamingModel(), Config())
    request = next(g for g in plan['lessons'][1:] if nodes['Application.dispatch']['id'] in g['node_ids'])
    setup = next(g for g in plan['lessons'][1:] if nodes['Application.configure']['id'] in g['node_ids'])
    assert request['id'] != setup['id']
    assert request['reading_order'].index(nodes['Application.__call__']['id']) < request['reading_order'].index(nodes['Application.dispatch']['id'])
    owner = {n: i for i, g in enumerate(plan['lessons'][1:]) for n in g['node_ids']}
    assert all(owner[e['target']] <= owner[e['source']] for e in inv['edges']
               if e['source'] in owner and e['target'] in owner)


def test_cycle_is_never_split_to_satisfy_size_limit():
    plan = make_plan(scan(FIXTURE), NamingModel(), Config(nodes_per_lesson=1))
    cycle = next(c for c in plan['cycles'] if len(c) > 1)
    groups = plan['lessons'][1:]
    key_cycle = set(cycle) & {n for g in groups for n in g['node_ids']}
    assert any(key_cycle <= set(g['node_ids']) for g in groups)


def test_module_dependencies_are_prioritized_without_blending_features(tmp_path):
    (tmp_path / 'base.py').write_text('def normalize(x): return x\n')
    (tmp_path / 'web.py').write_text('from base import normalize\n@route("/")\ndef endpoint(): return normalize(1)\n')
    inv = scan(tmp_path)
    p = make_plan(inv, NamingModel(), Config())
    groups = p['lessons'][1:]
    assert groups[0]['modules'] == ['base']
    assert groups[1]['modules'] == ['web']
    assert groups[0]['cohort'] < groups[1]['cohort']


def test_module_aggregation_cycle_is_explicit_co_requisite(tmp_path):
    (tmp_path / 'a.py').write_text('from b import leaf_b\ndef leaf_a(): return 1\ndef start_a(): return leaf_b()\n')
    (tmp_path / 'b.py').write_text('from a import leaf_a\ndef leaf_b(): return 2\ndef start_b(): return leaf_a()\n')
    p = make_plan(scan(tmp_path), NamingModel(), Config())
    features = p['lessons'][1:]
    assert len(features) == 2
    assert all(g['co_requisite'] for g in features)
    assert features[0]['cohort'] == features[1]['cohort']
    assert not p['cycles']


def test_curriculum_stable_across_hash_seeds():
    import os
    import subprocess
    import sys
    code = ('import json; from repo_tutor.scanner import scan; '
            'from repo_tutor.curriculum import group_lessons; '
            f'print(json.dumps(group_lessons(scan({str(FIXTURE)!r}), 3)))')
    results = [subprocess.check_output([sys.executable, '-c', code],
               env={**os.environ, 'PYTHONHASHSEED': seed}, text=True) for seed in ('17', '33')]
    assert json.loads(results[0]) == json.loads(results[1])

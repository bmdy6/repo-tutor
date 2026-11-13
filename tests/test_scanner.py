from pathlib import Path

from jsonschema import validate

from repo_tutor.graph import topology
from repo_tutor.scanner import scan, scan_schema

FIXTURE = Path(__file__).parent / 'fixtures/sample'


def test_inventory_and_source_schema():
    result = scan(FIXTURE)
    validate(result, scan_schema())
    nodes = {n['qualname']: n for n in result['nodes'] if n['path'].endswith('web.py')}
    assert nodes['hello']['entry'] == ['route']
    assert nodes['cli']['entry'] == ['cli', 'project-script']
    assert nodes['hello']['location'] == 'src/demo/web.py:4'
    assert any(n['kind'] == 'entry' for n in nodes.values())
    assert not next(n for n in result['nodes'] if n['name'] == '_private')['public']
    assert all(n['location'].endswith(':' + str(n['line'])) for n in result['nodes'])
    run = next(n for n in result['nodes'] if n['qualname'] == 'Service.run')
    clean = next(n for n in result['nodes'] if n['qualname'] == 'clean')
    assert any(e['source'] == run['id'] and e['target'] == clean['id'] and e['kind'] == 'call'
               for e in result['edges'])


def test_topology_dependencies_cycles_and_flows():
    result = scan(FIXTURE)
    graph = topology(result)
    position = {node: i for i, group in enumerate(graph['components']) for node in group}
    for edge in result['edges']:
        assert position[edge['target']] <= position[edge['source']]
    assert any(len(c) > 1 for c in graph['cycles'])
    hello = next(n for n in result['nodes'] if n['name'] == 'hello')
    assert any(f['entry'] == hello['id'] for f in graph['flows'])


def test_bad_source_and_symlinks_are_visible(tmp_path):
    (tmp_path / 'bad.py').write_text('def broken(:')
    (tmp_path / 'escape.py').symlink_to(FIXTURE / 'src/demo/util.py')
    result = scan(tmp_path)
    assert len(result['diagnostics']) == 2
    assert result['nodes'] == []


def test_topology_is_stable_across_hash_seeds():
    import json
    import os
    import subprocess
    import sys
    code = ('import json; from repo_tutor.scanner import scan; from repo_tutor.graph import topology; '
            f'print(json.dumps(topology(scan({str(FIXTURE)!r}))))')
    results = [subprocess.check_output([sys.executable, '-c', code],
               env={**os.environ, 'PYTHONHASHSEED': seed}, text=True) for seed in ('1', '2', '3')]
    assert all(json.loads(r) == json.loads(results[0]) for r in results)


def test_overloads_keep_unique_nodes_and_topology(tmp_path):
    (tmp_path / 'm.py').write_text('from typing import overload\n@overload\ndef convert(x: int): ...\n'
                                  '@overload\ndef convert(x: str): ...\ndef convert(x): return x\n')
    inv = scan(tmp_path)
    ids = [n['id'] for n in inv['nodes']]
    assert len(set(ids)) == len(ids)
    assert {i for c in topology(inv)['components'] for i in c} == set(ids)


def test_asgi_protocol_and_constructor_heuristics_respect_class_scope(tmp_path):
    (tmp_path / 'asgi.py').write_text('''class App:
    def __init__(self): pass
    async def __call__(self, scope, receive, send): pass
class _Internal:
    def __init__(self): pass
def factory():
    def __init__(): pass
    return __init__
''')
    inv = scan(tmp_path)
    validate(inv, scan_schema())
    nodes = {n['qualname']: n for n in inv['nodes']}
    assert nodes['App.__call__']['entry'] == ['protocol']
    assert nodes['App.__init__']['entry'] == ['constructor']
    assert nodes['_Internal.__init__']['entry'] == []
    assert nodes['factory.__init__']['entry'] == []

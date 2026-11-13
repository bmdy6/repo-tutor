"""Dependency-owned course groups, bounded evidence, and citation-bearing rendering."""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

from repo_tutor.config import Config
from repo_tutor.graph import topology
from repo_tutor.scanner import safe_source, source_text


def plain_text(value, limit=1200):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
        or any(c in value for c in ('\n', '\r', '```', '<', '>'))
        or re.search(r'\]\s*\(', value)
        or re.search(r'\S+\.py:\d+', value)):
        raise ValueError('model text must be bounded plain text, without links or source coordinates')
    return value.strip()


def fingerprint(inventory):
    return hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()


def make_plan(inventory: dict, model, config: Config) -> dict:
    graph = topology(inventory)
    nodes = {n['id']: n for n in inventory['nodes']}
    ordered = [identity for group in graph['components'] for identity in group
               if nodes[identity]['public'] or nodes[identity]['entry']]
    lessons = [{'id': f'{i // config.nodes_per_lesson + 1:02d}',
                'node_ids': ordered[i:i + config.nodes_per_lesson]}
               for i in range(0, len(ordered), config.nodes_per_lesson)]
    if not lessons:
        raise ValueError('no key Python symbols found')
    data = {'task': 'outline', 'policy': graph['policy'],
            'lessons': [{'id': x['id'], 'symbols': [{'id': n, 'name': nodes[n]['qualname'],
                         'source': nodes[n]['location'], 'docstring': (nodes[n]['docstring'] or '')[:160]}
                        for n in x['node_ids']]} for x in lessons]}
    prompt = json.dumps(data, ensure_ascii=False)
    if len(prompt) > config.max_context_chars:
        raise ValueError('outline context exceeds max_context_chars')
    response = model.complete(prompt)
    titles = response.get('titles', [])
    if (not isinstance(titles, list) or not all(isinstance(x, dict) for x in titles)
        or [x.get('id') for x in titles] != [x['id'] for x in lessons]):
        raise ValueError('outline titles must preserve every deterministic lesson ID in order')
    for lesson, title in zip(lessons, titles):
        lesson['title'] = plain_text(title.get('title'), 120)
    return {'schema_version': 1, 'inventory_sha256': fingerprint(inventory),
            'lessons': lessons, 'cycles': graph['cycles'], 'policy': graph['policy']}


def validate_plan(inventory, plan):
    if plan.get('inventory_sha256') != fingerprint(inventory):
        raise ValueError('plan does not match this inventory; run plan again')
    nodes = {n['id']: n for n in inventory['nodes']}
    expected = [i for group in topology(inventory)['components'] for i in group
                if nodes[i]['public'] or nodes[i]['entry']]
    actual = [i for lesson in plan['lessons'] for i in lesson['node_ids']]
    if actual != expected:
        raise ValueError('plan must preserve dependency order and key-node ownership')
    ids = [x['id'] for x in plan['lessons']]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r'\d{2,4}', i) for i in ids):
        raise ValueError('invalid lesson IDs')
    for lesson in plan['lessons']:
        plain_text(lesson['title'], 120)


def render_outline(inventory, plan):
    validate_plan(inventory, plan)
    nodes = {n['id']: n for n in inventory['nodes']}
    lines = ['# 课程大纲', '', '> 静态依赖优先。循环依赖组内仅使用稳定顺序；成员可能跨课，不能理解成严格先修关系。', '']
    for lesson in plan['lessons']:
        lines.extend([f"## {lesson['id']} · {lesson['title']}", ''])
        lines.extend(f"- [{nodes[n]['qualname']}]({nodes[n]['location']})" for n in lesson['node_ids'])
        lines.append('')
    lines.extend(['## 循环依赖', '', '```json', json.dumps(plan['cycles'], indent=2), '```', ''])
    return '\n'.join(lines)


def evidence(root, node, config):
    path = safe_source(Path(root), node['path'])
    lines = source_text(path).splitlines()
    start, end = node['line'] - 1, node['end_line']
    chosen = set(range(start, min(start + 7, end)))
    # Skip long leading docstrings to expose executable statements, retaining the header.
    snippet_tree = ast.parse(source_text(path))
    candidate = next((x for x in ast.walk(snippet_tree) if getattr(x, 'lineno', 0) == node['line']
                      and isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If))), None)
    body = getattr(candidate, 'body', [])
    first_body = body[1] if len(body) > 1 and isinstance(body[0], ast.Expr) and isinstance(
        body[0].value, ast.Constant) and isinstance(body[0].value.value, str) else body[0] if body else None
    if first_body:
        first = first_body.lineno - 1
        chosen.update(range(first, min(end, first + max(1, config.excerpt_lines - len(chosen)))))
    return {'id': node['id'], 'symbol': node['qualname'], 'location': node['location'],
            'entry': node['entry'], 'excerpt': '\n'.join(f'{i + 1}: {lines[i]}' for i in sorted(chosen)),
            'truncated': end - start > len(chosen)}


def write_lesson(root, inventory, plan, lesson_id, model, config):
    validate_plan(inventory, plan)
    lesson = next((x for x in plan['lessons'] if x['id'] == lesson_id), None)
    if lesson is None:
        raise ValueError('unknown lesson ID')
    for item in inventory['files']:
        if hashlib.sha256(safe_source(Path(root), item['path']).read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('source changed since scan; rescan before generation')
    nodes = {n['id']: n for n in inventory['nodes']}
    data = {'task': 'lesson', 'title': lesson['title'],
            'evidence': [evidence(root, nodes[n], config) for n in lesson['node_ids']],
            'policy': 'Only explain shown evidence. Snippets can be truncated; do not invent missing behavior.'}
    prompt = json.dumps(data, ensure_ascii=False)
    if len(prompt) > config.max_context_chars:
        raise ValueError('lesson context exceeds max_context_chars; reduce nodes_per_lesson')
    response = model.complete(prompt)
    facts = response.get('facts', [])
    if (not isinstance(facts, list) or not all(isinstance(x, dict) for x in facts)
        or [x.get('node_id') for x in facts] != lesson['node_ids']):
        raise ValueError('lesson facts must cover each assigned node exactly once in order')
    lines = [f"# {lesson_id} · {lesson['title']}", '',
             '> 模型生成，需人工审阅。仅依据静态源码片段；图中的边表示可解析的静态关系。', '', '## 从源码理解', '']
    for fact in facts:
        n = nodes[fact['node_id']]
        claim = plain_text(fact.get('claim'))
        lines.extend([f"- **{n['qualname']}**：{claim} [{n['qualname']}]({n['location']})", ''])
    lines.extend(['## 本课静态关系', '', '```mermaid', 'flowchart TD'])
    graph_nodes = {identity: f'n{i}' for i, identity in enumerate(lesson['node_ids'])}
    for identity, key in graph_nodes.items():
        n = nodes[identity]
        lines.append(f'  {key}["{n["qualname"]}"]')
    for edge in inventory['edges']:
        if edge['source'] in graph_nodes and edge['target'] in graph_nodes:
            lines.append(f'  {graph_nodes[edge["source"]]} -->|{edge["kind"]}| {graph_nodes[edge["target"]]}')
    lines.extend(['```', '', '> 孤立节点表示本课范围内没有解析到连边；不代表运行时无联系。', ''])
    return '\n'.join(lines)

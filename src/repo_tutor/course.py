"""Dependency-owned course groups, bounded evidence, and citation-bearing rendering."""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

from repo_tutor.config import Config
from repo_tutor.curriculum import group_lessons
from repo_tutor.diagrams import render_diagram
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
    skeleton = group_lessons(inventory, config.nodes_per_lesson)
    lessons = skeleton['lessons']
    nodes = {n['id']: n for n in inventory['nodes']}
    data = {'task': 'outline', 'policy': skeleton['policy'],
            'lessons': [{'id': x['id'], 'kind': x['kind'], 'modules': x['modules'], 'entries': x['entries'], 'symbols': [{'name': nodes[n]['qualname'],
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
    return {**skeleton, 'inventory_sha256': fingerprint(inventory)}


def validate_plan(inventory, plan):
    if plan.get('inventory_sha256') != fingerprint(inventory):
        raise ValueError('plan does not match this inventory; run plan again')
    if plan.get('schema_version') != 2:
        raise ValueError('old course plan; use a new output directory for schema v2 groups')
    limit = plan.get('group_size')
    if type(limit) is not int or limit < 1:
        raise ValueError('invalid group size')
    skeleton = group_lessons(inventory, limit)
    actual = [{k: v for k, v in lesson.items() if k != 'title'} for lesson in plan['lessons']]
    if actual != skeleton['lessons'] or plan.get('cycles') != skeleton['cycles'] or plan.get('policy') != skeleton['policy']:
        raise ValueError('plan must preserve deterministic groups, order and key-node ownership')
    for lesson in plan['lessons']:
        plain_text(lesson['title'], 120)


def render_outline(inventory, plan):
    validate_plan(inventory, plan)
    nodes = {n['id']: n for n in inventory['nodes']}
    lines = ['# 课程大纲', '', '> 模块与入口可达流程分组；调用/继承依赖优先。00 为全局导读。', '',
             '> 同一循环依赖 cohort 内是共同先修，稳定顺序不代表严格依赖顺序。', '',
             '分组规则：' + plan['policy'], '']
    for lesson in plan['lessons']:
        lines.extend([f"## {lesson['id']} · {lesson['title']}", ''])
        if lesson['kind'] == 'overview':
            lines.extend(['系统用途 → 入口 → 模块地图 → 一次典型调用（静态推断）。', ''])
        else:
            lines.extend([f"模块：{', '.join(lesson['modules'])}；cohort {lesson['cohort']}；"
                          f"共同先修：{lesson['co_requisite']}；功能分组第 {lesson['part']} 部分。", ''])
        lines.extend(f"- [{nodes[n]['qualname']}]({nodes[n]['location']})" for n in lesson['node_ids'])
        lines.append('')
    lines.extend(['## 节点循环依赖', '', '```json', json.dumps(plan['cycles'], indent=2), '```', ''])
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
            'entry': node['entry'], 'docstring': (node['docstring'] or '')[:1600], 'excerpt': '\n'.join(f'{i + 1}: {lines[i]}' for i in sorted(chosen)),
            'truncated': end - start > len(chosen)}


def lesson_evidence_ids(lesson, inventory):
    nodes = {n['id']: n for n in inventory['nodes']}
    if lesson['kind'] == 'overview':
        entries = [i for i in lesson['entries'] if 'constructor' not in nodes[i]['entry']]
        parents = [nodes[i]['parent'] for i in entries if nodes[i]['parent'] in nodes]
        return list(dict.fromkeys(lesson['reading_order'] + entries + parents + lesson['module_nodes']))
    module_ids = [i for i, n in nodes.items() if n['kind'] == 'module' and n['module'] in lesson['modules']]
    return list(dict.fromkeys(lesson['reading_order'] + module_ids))


def cited_text(item, allowed, nodes, field='text'):
    if not isinstance(item, dict):
        raise ValueError('course sections must contain objects')
    text = plain_text(item.get(field), 1800)
    ids = item.get('node_ids')
    if (not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i in allowed for i in ids)
        or len(set(ids)) != len(ids)):
        raise ValueError('paragraph and quiz citations must reference supplied evidence nodes')
    return text + ' ' + ' '.join(f"[{nodes[i]['qualname']}]({nodes[i]['location']})" for i in ids)


def write_lesson(root, inventory, plan, lesson_id, model, config):
    validate_plan(inventory, plan)
    lesson = next((x for x in plan['lessons'] if x['id'] == lesson_id), None)
    if lesson is None:
        raise ValueError('unknown lesson ID')
    for item in inventory['files']:
        if hashlib.sha256(safe_source(Path(root), item['path']).read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('source changed since scan; rescan before generation')
    nodes = {n['id']: n for n in inventory['nodes']}
    ids = lesson_evidence_ids(lesson, inventory)
    next_index = plan['lessons'].index(lesson) + 1
    following = plan['lessons'][next_index] if next_index < len(plan['lessons']) else None
    data = {'task': 'lesson', 'kind': lesson['kind'], 'title': lesson['title'],
            'modules': lesson['modules'], 'entries': lesson['entries'], 'lifecycle': lesson.get('lifecycle'),
            'reading_order': lesson['reading_order'],
            'required_response': {'goals': ['学习目标一', '学习目标二'],
                                  'paragraphs': [{'section': 'system/entries/modules/lifecycle' if lesson['kind'] == 'overview' else 'flow',
                                                  'text': '连贯的源码讲解段落', 'node_ids': ['COPY_ID_FROM_EVIDENCE']}],
                                  'quiz': [{'question': '问题一', 'answer': '答案一', 'node_ids': ['COPY_ID_FROM_EVIDENCE']},
                                           {'question': '问题二', 'answer': '答案二', 'node_ids': ['COPY_ID_FROM_EVIDENCE']}],
                                  'transition': '衔接下一课的一句话'},
            'evidence': [evidence(root, nodes[n], config) for n in ids],
            'edges': [e for e in inventory['edges'] if e['source'] in ids and e['target'] in ids],
            'next_title': following['title'] if following else None,
            'policy': plan['policy'] + ' Only explain shown evidence. Snippets may be truncated. '
                      'Write connected paragraphs about one flow/function, not one paragraph per symbol. '
                      'Use a representative path; the reference table supplies exhaustive key-node coverage. '
                      'This is task=lesson. Return goals, paragraphs, quiz, transition; never return titles.'}
    prompt = json.dumps(data, ensure_ascii=False)
    if len(prompt) > config.max_context_chars:
        raise ValueError('lesson context exceeds max_context_chars; reduce nodes_per_lesson or excerpt_lines')
    response = model.complete(prompt)
    goals, paragraphs, quiz = (response.get(k) for k in ('goals', 'paragraphs', 'quiz'))
    if not isinstance(goals, list) or not 2 <= len(goals) <= 3:
        raise ValueError('course needs 2-3 learning goals')
    if not isinstance(paragraphs, list) or not 2 <= len(paragraphs) <= 12:
        raise ValueError('course needs 2-12 connected paragraphs')
    if not isinstance(quiz, list) or len(quiz) != 2:
        raise ValueError('course needs exactly 2 quiz questions with answers')
    transition = plain_text(response.get('transition'), 300)
    allowed = set(ids)
    sections = ['system', 'entries', 'modules', 'lifecycle']
    if lesson['kind'] == 'overview':
        actual = [p.get('section') for p in paragraphs if isinstance(p, dict)]
        if list(dict.fromkeys(actual)) != sections:
            raise ValueError('overview paragraphs must cover system, entries, modules, lifecycle in order')
    lines = [f"# {lesson_id} · {lesson['title']}", '',
             '> 模型生成，需人工审阅。静态推断：可达关系与源码顺序不等于运行轨迹；动态分派仍需运行验证。', '',
             '## 学习目标', '']
    anchor = nodes[ids[0]]
    citation = f"[{anchor['qualname']}]({anchor['location']})"
    lines.extend(f'- {plain_text(goal, 240)} {citation}' for goal in goals)
    lines.extend(['', '## 按调用顺序理解', ''])
    section_titles = dict(zip(sections, ['系统做什么', '有哪些入口', '模块地图', '一次典型调用的生命周期']))
    last_section = None
    for paragraph in paragraphs:
        if lesson['kind'] == 'overview' and paragraph.get('section') != last_section:
            last_section = paragraph['section']
            lines.extend(['### ' + section_titles[last_section], ''])
            if last_section == 'modules':
                lines.extend([render_diagram(inventory, lesson['module_nodes'], module_map=True), ''])
            if last_section == 'lifecycle':
                if lesson['lifecycle'] is None:
                    lines.extend(['> 未识别入口，无法推导入口生命周期；以下图仅展示静态定义，不代表调用流程。', ''])
                elif lesson['lifecycle']['truncated']:
                    lines.extend(['> 入口可达集合达到扫描上限，生命周期子图已截断。', ''])
                flow_ids = lesson['reading_order'][:20] or [ids[0]]
                lines.extend([render_diagram(inventory, flow_ids), '',
                              '> 图为入口静态可达子图，至多展示 20 个节点；没有连边不代表运行时无联系。', ''])
        lines.extend([cited_text(paragraph, allowed, nodes), ''])
    if lesson['kind'] != 'overview':
        lines.extend([render_diagram(inventory, lesson['reading_order'][:20]), '',
                      '> 图只显示前 20 个阅读节点间可解析的调用/继承边；非运行时完整轨迹。', ''])
    lines.extend(['## 关键符号速查', '', '| 符号 | 类型 / 入口 | 出处 |', '| --- | --- | --- |'])
    table_ids = lesson['node_ids'] if lesson['kind'] != 'overview' else list(dict.fromkeys(
        lesson['reading_order'][:20] + [i for i in lesson['entries'] if 'constructor' not in nodes[i]['entry']]))
    if not table_ids:
        table_ids = [ids[0]]
    for identity in table_ids:
        n = nodes[identity]
        lines.append(f"| `{n['qualname']}` | {n['kind']} / {', '.join(n['entry']) or '—'} | "
                     f"[{n['qualname']}]({n['location']}) |")
    lines.extend(['', '## 自测题', ''])
    for number, item in enumerate(quiz, 1):
        lines.extend([f"{number}. " + cited_text(item, allowed, nodes, 'question'), '',
                      '答案：' + cited_text(item, allowed, nodes, 'answer'), ''])
    lines.extend(['## 下一课', ''])
    if following:
        target = following['node_ids'][0]
        n = nodes[target]
        lines.append(f"{transition} 下一课：{following['id']} · {following['title']}。 "
                     f"[{n['qualname']}]({n['location']})")
    else:
        lines.append(f'{transition} 课程结束，可回到全局导读复盘。 {citation}')
    lines.append('')
    return '\n'.join(lines)

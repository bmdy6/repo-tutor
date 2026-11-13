"""Mechanical citation and coverage checks; deliberately no semantic truth score."""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

from repo_tutor.scanner import safe_source, source_text

CITATION = re.compile(r'\[([^\]\n]+)\]\(([^\s()]+\.py):(\d+)\)')
COORDINATE = re.compile(r'([^\s`\[\]()<>]+\.py):(\d+)')


def symbol_lines(text: str) -> dict[str, list[int]]:
    result = {'<module>': [1]}
    def walk(obj, prefix=''):
        for child in ast.iter_child_nodes(obj):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = prefix + child.name
                result.setdefault(qual, []).append(child.lineno)
                walk(child, qual + '.')
            elif isinstance(child, ast.If) and ast.unparse(child.test) in {
                "__name__ == '__main__'", "'__main__' == __name__"}:
                result[f'<main@{child.lineno}>'] = [child.lineno]
                walk(child, prefix)
            else:
                walk(child, prefix)
    walk(ast.parse(text))
    return result


def verify(root: str | Path, inventory: dict, lessons: dict[str, str], proximity: int = 3) -> dict:
    root = Path(root).resolve(strict=True)
    key = {n['id']: n for n in inventory['nodes'] if n['public'] or n['entry']}
    nodes = inventory['nodes']
    covered, invalid, issues, drift = set(), [], [], []
    cache = {}
    for item in inventory['files']:
        try:
            p = safe_source(root, item['path'])
            if hashlib.sha256(p.read_bytes()).hexdigest() != item['sha256']:
                drift.append(item['path'])
        except (OSError, ValueError):
            drift.append(item['path'])
    total = 0
    for filename, lesson in sorted(lessons.items()):
        if filename in ('outline.md', 'README.md', 'verification.md'):
            continue
        matches = list(CITATION.finditer(lesson))
        total += len(matches)
        valid_spans = [(m.start(2), m.end(3)) for m in matches]
        for raw in COORDINATE.finditer(lesson):
            if not any(a <= raw.start() and raw.end() <= b for a, b in valid_spans):
                invalid.append({'lesson': filename, 'citation': raw.group(), 'reason': 'missing symbol label'})
        for match in matches:
            symbol, relative, line_string = match.groups()
            line = int(line_string)
            reason = None
            try:
                p = safe_source(root, relative)
                if relative not in cache:
                    text = source_text(p)
                    cache[relative] = (len(text.splitlines()), symbol_lines(text))
                length, actual_symbols = cache[relative]
                node = next((n for n in sorted(nodes, key=lambda n: abs(n['line'] - line))
                             if n['path'] == relative and n['qualname'] == symbol
                             and abs(n['line'] - line) <= proximity), None)
                if not 1 <= line <= length:
                    reason = 'line out of range'
                elif symbol not in actual_symbols or not any(abs(actual - line) <= proximity for actual in actual_symbols[symbol]):
                    reason = 'symbol not declared near cited line'
                elif node is None:
                    reason = 'symbol not present in scanned inventory'
                else:
                    covered.add(node['id'])
            except (ValueError, OSError, SyntaxError, UnicodeError, LookupError):
                reason = 'missing, unsafe or unparseable source file'
            if reason:
                invalid.append({'lesson': filename, 'citation': match.group(), 'reason': reason})
        in_fence = False
        for number, line in enumerate(lesson.splitlines(), 1):
            if line.startswith('```'):
                in_fence = not in_fence
            elif (not in_fence and line.strip() and not line.startswith(('#', '>'))
                  and not CITATION.search(line)):
                issues.append({'lesson': filename, 'line': number,
                               'reason': 'uncited prose; review whether factual'})
        if '```mermaid\n' not in lesson:
            issues.append({'lesson': filename, 'reason': 'missing mermaid diagram'})
    missing = [dict(id=n['id'], symbol=n['qualname'], location=n['location'])
               for identity, n in sorted(key.items()) if identity not in covered]
    return {'passed': not (invalid or missing or drift or issues or inventory['diagnostics']),
            'coverage': {'total': len(key), 'covered': len(set(key) & covered), 'missing': missing},
            'citations': {'total': total, 'invalid': invalid}, 'source_drift': sorted(drift),
            'lesson_issues': issues, 'scan_diagnostics': inventory['diagnostics'],
            'human_review_required': True,
            'disclaimer': '覆盖完整 ≠ 讲对了。引用有效仅表示文件、行号和附近符号有效；内容正确性需要人看。'
                          '无引用段落检查是启发式，不能判断每个事实是否被证据支持。'}


def report_markdown(report: dict) -> str:
    coverage = report['coverage']
    text = ['# 校验报告', '', report['disclaimer'], '',
            f"- 机械校验通过：{report['passed']}",
            f"- 关键节点覆盖：{coverage['covered']} / {coverage['total']}",
            f"- 无效引用：{len(report['citations']['invalid'])} / {report['citations']['total']}",
            f"- 源码漂移：{len(report['source_drift'])}",
            f"- 课文结构问题：{len(report['lesson_issues'])}",
            f"- 扫描诊断：{len(report['scan_diagnostics'])}", '', '## 漏讲节点', '']
    text.extend(f"- {n['symbol']} — `{n['location']}`" for n in coverage['missing'])
    if not coverage['missing']:
        text.append('无。')
    text.extend(['', '## 无效引用与其他问题', ''])
    for field in ('citations', 'lesson_issues', 'source_drift', 'scan_diagnostics'):
        values = report[field]['invalid'] if field == 'citations' else report[field]
        text.extend(f'- {item}' for item in values)
    return '\n'.join(text).rstrip() + '\n'

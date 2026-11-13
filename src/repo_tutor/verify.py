"""Mechanical citation and coverage checks; deliberately no semantic truth score."""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

from repo_tutor.diagrams import diagram_issues
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


SECTIONS = ('学习目标', '按调用顺序理解', '关键符号速查', '自测题', '下一课')


def lesson_structure(text, filename):
    issues, zones, content = [], [], {section: [] for section in SECTIONS}
    section, in_fence, offset = None, False, 0
    headings = []
    lines = text.splitlines(keepends=True)
    for index, raw in enumerate(lines):
        line = raw.rstrip('\r\n')
        if line.startswith('```'):
            in_fence = not in_fence
        elif not in_fence:
            if line.startswith('## '):
                section = line[3:].strip()
                headings.append(section)
            elif line.strip() and not line.startswith(('#', '>')):
                if section in content:
                    content[section].append(line)
                is_header = (line.startswith('|') and index + 1 < len(lines)
                             and re.fullmatch(r'[| :\-]+\s*', lines[index + 1]))
                is_separator = bool(re.fullmatch(r'[| :\-]+', line))
                if not is_header and not is_separator:
                    if not CITATION.search(line):
                        issues.append({'line': index + 1, 'reason': 'uncited prose; review whether factual'})
                    zone = ('narrative' if section == '按调用顺序理解' and not line.startswith('|')
                            else 'table' if section == '关键符号速查' and line.startswith('|') else 'other')
                    zones.append((offset, offset + len(raw), zone))
        offset += len(raw)
    if headings != list(SECTIONS):
        issues.append({'reason': 'missing, duplicate or out-of-order course section'})
    if not 2 <= sum(line.startswith('- ') for line in content['学习目标']) <= 3:
        issues.append({'reason': 'learning goals must number 2-3'})
    if ([re.match(r'^([12])\. ', line)[1] for line in content['自测题']
         if re.match(r'^([12])\. ', line)] != ['1', '2']
        or sum(line.startswith('答案：') for line in content['自测题']) != 2):
        issues.append({'reason': 'quiz must have 2 questions and 2 answers'})
    if any(not content[s] for s in ('按调用顺序理解', '关键符号速查', '下一课')):
        issues.append({'reason': 'empty course section'})
    if filename == '00.md':
        for heading in ('系统做什么', '有哪些入口', '模块地图', '一次典型调用的生命周期'):
            if '### ' + heading not in text:
                issues.append({'reason': 'missing overview section: ' + heading})
    return issues, zones


def verify(root: str | Path, inventory: dict, lessons: dict[str, str], proximity: int = 3) -> dict:
    root = Path(root).resolve(strict=True)
    key = {n['id']: n for n in inventory['nodes'] if n['public'] or n['entry']}
    nodes = inventory['nodes']
    covered, invalid, issues, drift = set(), [], [], []
    appearances = {zone: set() for zone in ('narrative', 'table', 'other')}
    per_lesson = {}
    cache = {}
    for item in inventory['files']:
        try:
            p = safe_source(root, item['path'])
            if hashlib.sha256(p.read_bytes()).hexdigest() != item['sha256']:
                drift.append(item['path'])
        except (OSError, ValueError):
            drift.append(item['path'])
    total = 0
    if '00.md' not in lessons:
        issues.append({'lesson': '00.md', 'reason': 'missing global overview lesson'})
    for filename, lesson in sorted(lessons.items()):
        if filename in ('outline.md', 'README.md', 'verification.md'):
            continue
        structure, zones = lesson_structure(lesson, filename)
        issues.extend({'lesson': filename, **item} for item in structure)
        issues.extend({'lesson': filename, 'reason': reason} for reason in diagram_issues(lesson, inventory))
        local = {zone: set() for zone in appearances}
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
                    zone = next((zone for a, b, zone in zones if a <= match.start() < b), None)
                    if zone:
                        covered.add(node['id'])
                        appearances[zone].add(node['id'])
                        local[zone].add(node['id'])
            except (ValueError, OSError, SyntaxError, UnicodeError, LookupError):
                reason = 'missing, unsafe or unparseable source file'
            if reason:
                invalid.append({'lesson': filename, 'citation': match.group(), 'reason': reason})
        per_lesson[filename] = coverage_counts(local, set(key))
    missing = [dict(id=n['id'], symbol=n['qualname'], location=n['location'])
               for identity, n in sorted(key.items()) if identity not in covered]
    return {'passed': not (invalid or missing or drift or issues or inventory['diagnostics']),
            'coverage': {'total': len(key), 'covered': len(set(key) & covered), 'missing': missing,
                         **coverage_counts(appearances, set(key))}, 'lesson_coverage': per_lesson,
            'citations': {'total': total, 'invalid': invalid}, 'source_drift': sorted(drift),
            'lesson_issues': issues, 'scan_diagnostics': inventory['diagnostics'],
            'human_review_required': True,
            'disclaimer': '覆盖完整 ≠ 讲对了。引用有效仅表示文件、行号和附近符号有效；内容正确性需要人看。'
                          '无引用段落检查是启发式，不能判断每个事实是否被证据支持。'}


def coverage_counts(appearances, key):
    narrative = appearances['narrative'] & key
    reference = (appearances['table'] - narrative - appearances['other']) & key
    other = (set.union(*appearances.values()) & key) - narrative - reference
    return {'narrative': len(narrative), 'reference_only': len(reference), 'other_only': len(other),
            'narrative_nodes': sorted(narrative), 'reference_only_nodes': sorted(reference),
            'other_only_nodes': sorted(other)}


def report_markdown(report: dict) -> str:
    coverage = report['coverage']
    text = ['# 校验报告', '', report['disclaimer'], '',
            f"- 机械校验通过：{report['passed']}",
            f"- 关键节点覆盖：{coverage['covered']} / {coverage['total']}",
            f"- 在讲解段落中出现：{coverage['narrative']}",
            f"- 只在速查表出现：{coverage['reference_only']}",
            f"- 其他位置覆盖（目标/自测/衔接等，未进入讲解）：{coverage['other_only']}",
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

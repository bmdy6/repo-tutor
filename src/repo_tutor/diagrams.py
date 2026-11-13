"""Canonical Mermaid nodes are identities from the scanned inventory, never model text."""
from __future__ import annotations

import hashlib
import html
import re


def diagram_id(identity):
    return 'n' + hashlib.sha256(identity.encode()).hexdigest()[:16]


def diagram_label(node):
    return html.escape(node['module'] + '.' + node['qualname'], quote=True)


def render_diagram(inventory, identities, module_map=False):
    nodes = {n['id']: n for n in inventory['nodes']}
    selected = list(dict.fromkeys(identities))
    lines = ['```mermaid', 'flowchart TD']
    lines.extend(f'  {diagram_id(i)}["{diagram_label(nodes[i])}"]' for i in selected)
    edges = set()
    if module_map:
        module_ids = {nodes[i]['module']: i for i in selected}
        for e in inventory['edges']:
            source = module_ids.get(nodes[e['source']]['module'])
            target = module_ids.get(nodes[e['target']]['module'])
            if e['kind'] == 'import' and source and target and source != target:
                edges.add((source, target, 'import'))
    else:
        for e in inventory['edges']:
            if e['source'] in selected and e['target'] in selected and e['kind'] != 'import':
                edges.add((e['source'], e['target'], e['kind']))
    lines.extend(f'  {diagram_id(a)} -->|{kind}| {diagram_id(b)}' for a, b, kind in sorted(edges))
    lines.append('```')
    return '\n'.join(lines)


def diagram_issues(text, inventory):
    """Accept our small diagram grammar; fail closed on unknown nodes or hidden endpoints."""
    known = {diagram_id(n['id']): diagram_label(n) for n in inventory['nodes']}
    blocks = re.findall(r'^```mermaid\s*\n(.*?)^```\s*$', text, re.M | re.S)
    if not blocks:
        return ['missing mermaid diagram']
    issues = []
    if len(re.findall(r'^```mermaid', text, re.M)) != len(blocks):
        issues.append('unclosed or malformed mermaid diagram')
    for block in blocks:
        declared, endpoints = set(), set()
        if not block.strip().startswith(('flowchart TD\n', 'flowchart LR\n')):
            issues.append('missing diagram flowchart header')
        for line in block.splitlines():
            line = line.strip()
            if not line or line in ('flowchart TD', 'flowchart LR'):
                continue
            declaration = re.fullmatch(r'(n[0-9a-f]{16})\["([^"]+)"\]', line)
            edge = re.fullmatch(r'(n[0-9a-f]{16}) -->\|(call|inherit|import)\| (n[0-9a-f]{16})', line)
            if declaration:
                identity, label = declaration.groups()
                if identity not in known or known[identity] != label:
                    issues.append('diagram node not present in scanned inventory')
                if identity in declared:
                    issues.append('duplicate diagram node declaration')
                declared.add(identity)
            elif edge:
                endpoints.update((edge[1], edge[3]))
            else:
                issues.append('unsupported diagram syntax or unknown node')
        if not declared:
            issues.append('empty diagram')
        if endpoints - declared:
            issues.append('undeclared diagram endpoint')
    return sorted(set(issues))

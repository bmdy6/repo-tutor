"""Dependency-first SCC order and bounded entry reachability."""
from __future__ import annotations

from graphlib import TopologicalSorter


def topology(inventory: dict, max_flow_nodes: int = 100) -> dict:
    adjacency = {n['id']: set() for n in inventory['nodes']}
    for edge in inventory['edges']:
        adjacency[edge['source']].add(edge['target'])
    # Iterative Kosaraju avoids Python recursion limits on large repositories.
    seen, finished = set(), []
    for start in sorted(adjacency):
        if start in seen:
            continue
        stack = [(start, False)]
        while stack:
            node, done = stack.pop()
            if done:
                finished.append(node)
            elif node not in seen:
                seen.add(node)
                stack.append((node, True))
                stack.extend((n, False) for n in sorted(adjacency[node], reverse=True) if n not in seen)
    reverse = {n: set() for n in adjacency}
    for node, targets in adjacency.items():
        for target in targets:
            reverse[target].add(node)
    seen, components = set(), []
    for start in reversed(finished):
        if start in seen:
            continue
        component, stack = [], [start]
        seen.add(start)
        while stack:
            node = stack.pop()
            component.append(node)
            for target in sorted(reverse[node]):
                if target not in seen:
                    seen.add(target)
                    stack.append(target)
        components.append(sorted(component))
    owner = {n: i for i, group in enumerate(components) for n in group}
    deps = {i: set() for i in range(len(components))}
    for node, targets in adjacency.items():
        deps[owner[node]].update(owner[t] for t in targets if owner[t] != owner[node])
    sorter = TopologicalSorter(deps)
    sorter.prepare()
    ordered = []
    while sorter.is_active():
        ready = sorted(sorter.get_ready(), key=lambda i: components[i][0])
        ordered.extend(components[i] for i in ready)
        sorter.done(*ready)
    flows = []
    for entry in (n for n in inventory['nodes'] if n['entry']):
        visited, queue = {entry['id']}, [entry['id']]
        while queue and len(visited) < max_flow_nodes:
            current = queue.pop(0)
            for target in sorted(adjacency[current]):
                if target not in visited:
                    if len(visited) >= max_flow_nodes:
                        break
                    visited.add(target)
                    queue.append(target)
        flows.append({'entry': entry['id'], 'nodes': sorted(visited),
                      'edges': [e for e in inventory['edges']
                                if e['source'] in visited and e['target'] in visited],
                      'truncated': any(t not in visited for n in visited for t in adjacency[n])})
    return {'components': ordered,
            'cycles': [c for c in ordered if len(c) > 1 or c[0] in adjacency[c[0]]],
            'flows': flows,
            'policy': 'Dependencies first; cycles are SCCs, members sorted by stable ID; '
                      'static reachability is not runtime execution order.'}

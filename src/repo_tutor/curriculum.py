"""Deterministic module/entry clusters, quotient SCC ordering and reading walks."""
from __future__ import annotations

from collections import deque

from repo_tutor.graph import topology

POLICY = ('Cluster by module, splitting route/protocol reachable subgraphs using nearest entry '
          '(distance, stable ID tie-break). Constructors/CLI remain with their module feature. '
          'Imports describe the module map; lesson prerequisites use call/inherit edges. '
          'Order quotient SCC cohorts dependency-first; cycles are co-requisites in stable cluster order. '
          'Soft size limit never splits a node SCC. Reading DFS uses call-site source order; '
          'static reachability is not runtime execution order.')


def reading_walk(ids, entries, inventory):
    """Entry-first DFS; outgoing calls ordered by source position, cycles visited once."""
    allowed = set(ids)
    outgoing = {i: [] for i in allowed}
    incoming = set()
    for edge in inventory['edges']:
        if edge['kind'] == 'call' and edge['source'] in allowed and edge['target'] in allowed:
            outgoing[edge['source']].append(edge)
            incoming.add(edge['target'])
    result, seen = [], set()
    nodes = {n['id']: n for n in inventory['nodes']}
    def source_order(i):
        return nodes[i]['path'], nodes[i]['line'], i
    starts = (sorted(set(entries) & allowed, key=source_order)
              + sorted(allowed - incoming, key=source_order) + sorted(allowed, key=source_order))
    for start in starts:
        stack = [start]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            result.append(node)
            edges = sorted(outgoing[node], key=lambda e: (int(e['location'].rsplit(':', 1)[1]), e['target']))
            stack.extend(e['target'] for e in reversed(edges))
    return result


def group_lessons(inventory, limit):
    graph = topology(inventory)
    nodes = {n['id']: n for n in inventory['nodes']}
    key = {i for i, n in nodes.items() if n['public'] or n['entry']}
    if not key:
        raise ValueError('no key Python symbols found')
    seeds = sorted(i for i, n in nodes.items() if n['entry'])
    flow_seeds = [i for i in seeds if set(nodes[i]['entry']) & {'route', 'protocol'}]
    outgoing = {i: set() for i in nodes}
    for e in inventory['edges']:
        if e['kind'] in ('call', 'inherit'):
            outgoing[e['source']].add(e['target'])
    nearest = {}
    for seed in flow_seeds:
        queue = deque([(seed, 0)])
        seen = {seed}
        while queue:
            current, distance = queue.popleft()
            candidate = (distance, seed)
            nearest[current] = min(nearest.get(current, candidate), candidate)
            for target in sorted(outgoing[current]):
                if target not in seen and nodes[target]['module'] == nodes[seed]['module']:
                    seen.add(target)
                    queue.append((target, distance + 1))
    owner = {i: n['module'] + '::' + (nearest[i][1] if i in nearest else '<module-feature>')
             for i, n in nodes.items()}
    # A real cross-cluster call cycle is an indivisible flow of its own, not a reason
    # to blend every other symbol in those modules into one giant mixed lesson.
    for component in graph['cycles']:
        if len({owner[i] for i in component}) > 1:
            for i in component:
                owner[i] = 'cycle::' + component[0]
    cluster_ids = sorted(set(owner.values()))
    quotient = {'nodes': [{'id': i, 'entry': []} for i in cluster_ids],
                'edges': [{'source': owner[e['source']], 'target': owner[e['target']]}
                          for e in inventory['edges'] if e['kind'] != 'import'
                          and owner[e['source']] != owner[e['target']]]}
    quotient_graph = topology(quotient)
    lessons = []
    for cohort, clusters in enumerate(quotient_graph['components']):
        for cluster in clusters:
            members = {i for i in nodes if owner[i] == cluster}
            units = [[i for i in component if i in key and i in members] for component in graph['components']]
            chunks, chunk = [], []
            for unit in (u for u in units if u):
                if chunk and len(chunk) + len(unit) > limit:
                    chunks.append(chunk)
                    chunk = []
                chunk.extend(unit)
            if chunk:
                chunks.append(chunk)
            for index, chunk in enumerate(chunks):
                support = sorted(i for i in members - key if nodes[i]['kind'] != 'module') if len(chunks) == 1 else []
                entries = sorted(set(chunk) & set(seeds))
                lessons.append({'id': f'{len(lessons) + 1:02d}', 'kind': 'feature', 'node_ids': chunk,
                                'modules': sorted({nodes[i]['module'] for i in chunk}),
                                'entries': entries, 'cluster_keys': [cluster], 'part': index + 1,
                                'cohort': cohort, 'co_requisite': len(clusters) > 1,
                                'merged_cycle': cluster.startswith('cycle::'),
                                'reading_order': reading_walk(chunk + support, entries, inventory)})
    # Include all module nodes in orientation; choose a deterministic largest entry call subgraph.
    flows = [f for f in graph['flows'] if 'protocol' in nodes[f['entry']]['entry']]
    if not flows:
        flows = [f for f in graph['flows'] if 'constructor' not in nodes[f['entry']]['entry']]
    if not flows:
        flows = graph['flows']
    flow = min(flows, key=lambda f: (-len(f['nodes']), f['entry'])) if flows else None
    map_nodes = sorted(i for i, n in nodes.items() if n['kind'] == 'module')
    flow_ids = reading_walk(flow['nodes'], [flow['entry']], inventory) if flow else []
    overview = {'id': '00', 'kind': 'overview', 'node_ids': [], 'modules': sorted({n['module'] for n in nodes.values()}),
                'entries': seeds, 'module_nodes': map_nodes, 'lifecycle': flow,
                'reading_order': flow_ids}
    return {'schema_version': 2, 'group_size': limit, 'lessons': [overview] + lessons,
            'cycles': graph['cycles'], 'policy': POLICY}

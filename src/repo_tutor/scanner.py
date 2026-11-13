"""AST-only inventory and conservative name resolution. Never imports target code."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import tokenize
import tomllib
from pathlib import Path

DEFAULT_EXCLUDES = ('.git', '.venv', 'venv', '__pycache__', 'build', 'dist', 'tests', 'docs', 'examples')
ROUTES = {'route', 'get', 'post', 'put', 'patch', 'delete', 'websocket', 'api_route'}


def scan_schema() -> dict:
    return json.loads(Path(__file__).with_name('scan.schema.json').read_text())


def source_text(path: Path) -> str:
    with tokenize.open(path) as stream:
        return stream.read()


def safe_source(root: Path, relative: str) -> Path:
    p = Path(relative)
    if p.is_absolute() or '..' in p.parts or not p.parts:
        raise ValueError('source path must be repository-relative')
    current = root.resolve()
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('symlink source paths are not allowed')
    current.resolve().relative_to(root.resolve())
    return current


def scan(root: str | Path, excludes=DEFAULT_EXCLUDES, max_file_bytes: int = 1_000_000) -> dict:
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('repository must be a directory')
    result = {'schema_version': 1, 'files': [], 'nodes': [], 'edges': [],
              'unresolved': [], 'diagnostics': []}
    modules, trees, bindings, module_ids, objects = {}, {}, {}, {}, {}
    source_roots = [root]
    if (root / 'src').is_dir() and not (root / 'src').is_symlink():
        source_roots.insert(0, root / 'src')
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in excludes and not d.startswith('.')
                         and not (Path(base) / d).is_symlink())
        for filename in sorted(files):
            if not filename.endswith('.py'):
                continue
            path = Path(base) / filename
            relative = path.relative_to(root).as_posix()
            try:
                safe_source(root, relative)
                if path.stat().st_size > max_file_bytes:
                    raise ValueError('file exceeds max_file_bytes')
                text = source_text(path)
                tree = ast.parse(text, filename=relative)
            except (ValueError, OSError, SyntaxError, UnicodeError, LookupError) as exc:
                result['diagnostics'].append({'path': relative, 'message': str(exc)})
                continue
            source_root = next(s for s in source_roots if path.is_relative_to(s))
            parts = list(path.relative_to(source_root).with_suffix('').parts)
            is_package = parts[-1] == '__init__'
            if is_package:
                parts.pop()
            module = '.'.join(parts)
            if module in modules:
                result['diagnostics'].append({'path': relative, 'message': 'ambiguous module name'})
                continue
            modules[module] = relative
            trees[relative] = tree
            bindings[module] = {}
            result['files'].append({'path': relative, 'module': module,
                                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                    'lines': len(text.splitlines())})
            module_id = relative + '::<module>@1'
            module_ids[module] = module_id

            def add(obj, qualname, kind, parent=None, entry=None):
                line = getattr(obj, 'lineno', 1)
                name = qualname.rsplit('.', 1)[-1]
                node = {'id': relative + '::' + qualname + '@' + str(line), 'name': name, 'qualname': qualname,
                        'module': module, 'path': relative, 'line': line,
                        'end_line': getattr(obj, 'end_lineno', None) or max(1, len(text.splitlines())),
                        'location': f'{relative}:{line}', 'kind': kind,
                        'docstring': ast.get_docstring(obj) if kind != 'entry' else None,
                        'public': kind in ('class', 'function') and all(
                            not part.startswith('_') for part in qualname.split('.')),
                        'entry': entry or [], 'parent': parent}
                result['nodes'].append(node)
                objects[node['id']] = obj
                return node['id']

            add(tree, '<module>', 'module')

            def definitions(body, prefix='', parent=module_id):
                for obj in body:
                    if isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        qual = prefix + obj.name
                        entry = []
                        if (isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and isinstance(objects.get(parent), ast.ClassDef) and prefix and all(
                            not part.startswith('_') for part in prefix.rstrip('.').split('.'))):
                            if obj.name == '__init__':
                                entry.append('constructor')
                            arguments = {a.arg for a in obj.args.args + obj.args.posonlyargs}
                            if obj.name == '__call__' and ({'environ', 'start_response'} <= arguments
                                                         or {'scope', 'receive', 'send'} <= arguments):
                                entry.append('protocol')
                        for dec in obj.decorator_list:
                            fn = dec.func if isinstance(dec, ast.Call) else dec
                            tail = ast.unparse(fn).split('.')[-1]
                            if tail in ROUTES:
                                entry.append('route')
                            if tail in {'command', 'group'}:
                                entry.append('cli')
                        node_id = add(obj, qual, 'class' if isinstance(obj, ast.ClassDef)
                                      else 'function', parent, sorted(set(entry)))
                        definitions(obj.body, qual + '.', node_id)
                    elif isinstance(obj, ast.If) and ast.unparse(obj.test) in {
                        "__name__ == '__main__'", "'__main__' == __name__"}:
                        add(obj, f'<main@{obj.lineno}>', 'entry', parent, ['main'])
                        definitions(obj.body, prefix, parent)
                    else:
                        # Includes conditional definitions, but not nested scopes twice.
                        for field in ('body', 'orelse', 'finalbody'):
                            value = getattr(obj, field, None)
                            if isinstance(value, list):
                                definitions(value, prefix, parent)
            definitions(tree.body)
            package = module if is_package else module.rpartition('.')[0]
            for obj in ast.walk(tree):
                if isinstance(obj, ast.Import):
                    for alias in obj.names:
                        bindings[module][alias.asname or alias.name.split('.')[0]] = (
                            alias.name if alias.asname else alias.name.split('.')[0])
                elif isinstance(obj, ast.ImportFrom):
                    if obj.level:
                        chunks = package.split('.') if package else []
                        base_parts = chunks[:len(chunks) - obj.level + 1]
                        import_base = '.'.join(base_parts + ([obj.module] if obj.module else []))
                    else:
                        import_base = obj.module or ''
                    for alias in obj.names:
                        if alias.name != '*':
                            bindings[module][alias.asname or alias.name] = f'{import_base}.{alias.name}'.strip('.')

    by_id = {n['id']: n for n in result['nodes']}
    symbols = {f"{n['module']}.{n['qualname']}": n['id'] for n in result['nodes']
               if n['kind'] in ('function', 'class')}

    def resolve(name, seen=None):
        seen = set() if seen is None else seen
        if name in seen:
            return None
        seen.add(name)
        if name in symbols:
            return symbols[name]
        if name in module_ids:
            return module_ids[name]
        parts = name.split('.')
        for i in range(len(parts) - 1, 0, -1):
            mod = '.'.join(parts[:i])
            if mod in bindings and parts[i] in bindings[mod]:
                target = bindings[mod][parts[i]] + ('.' + '.'.join(parts[i + 1:]) if parts[i + 1:] else '')
                return resolve(target, seen)
        return None

    edge_set = set()

    def edge(source, target, kind, line):
        item = (source, target, kind, line)
        if item not in edge_set:
            edge_set.add(item)
            result['edges'].append({'source': source, 'target': target, 'kind': kind,
                                    'location': f"{by_id[source]['path']}:{line}"})

    for node in result['nodes']:
        obj = objects[node['id']]
        mod = node['module']
        if node['kind'] == 'module':
            for target in bindings[mod].values():
                resolved = resolve(target)
                if resolved:
                    edge(node['id'], resolved, 'import', 1)
        if node['kind'] == 'class':
            for base in obj.bases:
                text = ast.unparse(base)
                first, _, tail = text.partition('.')
                resolved = resolve(bindings[mod].get(first, f'{mod}.{first}') + ('.' + tail if tail else ''))
                if resolved:
                    edge(node['id'], resolved, 'inherit', obj.lineno)
        # Do not attribute child bodies to enclosing function/class/module.
        def calls(current):
            for child in ast.iter_child_nodes(current):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if node['kind'] == 'module' and isinstance(child, ast.If) and any(
                    n['kind'] == 'entry' and n['path'] == node['path'] and n['line'] == child.lineno
                    for n in result['nodes']):
                    continue
                if isinstance(child, ast.Call):
                    yield child
                yield from calls(child)
        for call in calls(obj):
            name = ast.unparse(call.func)
            candidates = []
            first, _, tail = name.partition('.')
            if first in ('self', 'cls') and node['parent'] in by_id:
                parent = by_id[node['parent']]
                candidates.append(f"{mod}.{parent['qualname']}.{tail}")
            prefix = node['qualname'].split('.')[:-1]
            for depth in range(len(prefix), -1, -1):
                candidates.append('.'.join([mod] + prefix[:depth] + [name]))
            if first in bindings[mod]:
                candidates.append(bindings[mod][first] + ('.' + tail if tail else ''))
            resolved = next((r for c in candidates if (r := resolve(c))), None)
            if resolved:
                edge(node['id'], resolved, 'call', call.lineno)
            else:
                result['unresolved'].append({'source': node['id'], 'expression': name,
                                             'location': f"{node['path']}:{call.lineno}"})
    project = root / 'pyproject.toml'
    if project.is_file() and not project.is_symlink():
        try:
            metadata = tomllib.loads(project.read_text())
            for name, target in metadata.get('project', {}).get('scripts', {}).items():
                resolved = resolve(target.replace(':', '.'))
                if resolved:
                    by_id[resolved]['entry'] = sorted(set(by_id[resolved]['entry'] + ['project-script']))
        except (ValueError, OSError, TypeError, AttributeError) as exc:
            result['diagnostics'].append({'path': 'pyproject.toml', 'message': str(exc)})
    result['nodes'].sort(key=lambda n: (n['path'], n['line'], n['id']))
    result['edges'].sort(key=lambda e: (e['source'], e['target'], e['kind'], e['location']))
    return result

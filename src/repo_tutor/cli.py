"""Command-line orchestration: local artifacts are explicit; only plan/write call models."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import ValidationError, validate

from repo_tutor.config import load_config
from repo_tutor.course import make_plan, render_outline, validate_plan, write_lesson
from repo_tutor.graph import topology
from repo_tutor.model import ModelClient, save_json
from repo_tutor.scanner import scan, scan_schema
from repo_tutor.verify import report_markdown, verify


def output_file(directory: Path, name: str) -> Path:
    path = directory / name
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('output paths cannot contain symlinks')
    directory.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path):
    return json.loads(path.read_text())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='repo-tutor', description='Source-linked Python onboarding courses')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('scan', 'plan', 'write', 'verify', 'all'):
        cmd = sub.add_parser(command)
        cmd.add_argument('repository', type=Path)
        cmd.add_argument('--out', type=Path, default=Path('.repo-tutor'))
        cmd.add_argument('--config', type=Path)
        if command in ('write', 'all'):
            cmd.add_argument('--lessons', help='Comma-separated lesson IDs; default all; existing lessons are kept')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        root = args.repository.resolve(strict=True)
        # Check output ancestry before reading/writing any artifacts.
        output_file(args.out, 'scan.json')
        if args.command in ('scan', 'all'):
            inventory = scan(root, config.excludes, config.max_file_bytes)
            validate(inventory, scan_schema())
            save_json(output_file(args.out, 'scan.json'), inventory)
            save_json(output_file(args.out, 'topology.json'), topology(inventory))
        else:
            inventory = read_json(args.out / 'scan.json')
            validate(inventory, scan_schema())
        if args.command in ('plan', 'all'):
            if (args.out / 'plan.json').exists():
                plan = read_json(args.out / 'plan.json')
                validate_plan(inventory, plan)
            else:
                plan = make_plan(inventory, ModelClient(config, output_file(args.out, 'usage.json')), config)
                save_json(output_file(args.out, 'plan.json'), plan)
            output_file(args.out, 'outline.md').write_text(render_outline(inventory, plan))
        if args.command in ('write', 'all'):
            plan = read_json(args.out / 'plan.json')
            validate_plan(inventory, plan)
            selected = args.lessons.split(',') if args.lessons else [x['id'] for x in plan['lessons']]
            if set(selected) - {x['id'] for x in plan['lessons']}:
                raise ValueError('unknown lesson IDs')
            client = ModelClient(config, output_file(args.out, 'usage.json'))
            for lesson_id in selected:
                path = output_file(args.out / 'lessons', lesson_id + '.md')
                if not path.exists():
                    print(f'Writing lesson {lesson_id}', file=sys.stderr, flush=True)
                    path.write_text(write_lesson(root, inventory, plan, lesson_id, client, config))
        if args.command in ('verify', 'all'):
            lessons_dir = args.out / 'lessons'
            lessons = {p.name: p.read_text() for p in sorted(lessons_dir.glob('*.md')) if not p.is_symlink()}
            report = verify(root, inventory, lessons, config.citation_proximity)
            save_json(output_file(args.out, 'verification.json'), report)
            output_file(args.out, 'verification.md').write_text(report_markdown(report))
            print(f"Covered {report['coverage']['covered']}/{report['coverage']['total']}; "
                  f"invalid citations {len(report['citations']['invalid'])}; human review required")
            return 0 if report['passed'] else 1
        print(f'{args.command}: artifacts in {args.out}')
        return 0
    except ValidationError:
        print('repo-tutor: invalid scan.json schema; run scan again', file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        # Config/API errors intentionally contain no provider response body.
        print(f'repo-tutor: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

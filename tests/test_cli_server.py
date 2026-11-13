import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from test_generation import FakeModel

from repo_tutor.cli import main

FIXTURE = Path(__file__).parent / 'fixtures/sample'


def test_cli_all_and_verify_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr('repo_tutor.cli.ModelClient', lambda *args: FakeModel())
    out = tmp_path / 'course'
    assert main(['all', str(FIXTURE), '--out', str(out)]) == 0
    assert (out / 'scan.json').exists()
    assert (out / 'outline.md').exists()
    assert json.loads((out / 'verification.json').read_text())['passed']
    (out / 'lessons/01.md').write_text('No source citations here.\n')
    assert main(['verify', str(FIXTURE), '--out', str(out)]) == 1


def test_real_stdio_mcp_tools_are_read_only(tmp_path):
    before = sorted(str(p.relative_to(FIXTURE)) for p in FIXTURE.rglob('*'))
    async def run():
        params = StdioServerParameters(command=sys.executable, args=['-m', 'repo_tutor.server'],
                                       env={**os.environ, 'REPO_TUTOR_API_KEY': ''})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert {t.name for t in listed.tools} == {'scan_repository', 'inspect_topology', 'verify_course'}
                assert all(t.annotations.readOnlyHint is True for t in listed.tools)
                result = await session.call_tool('scan_repository', {'path': str(FIXTURE.resolve())})
                assert not result.isError
                inventory = json.loads(result.content[0].text)
                assert inventory['nodes']
                graph = await session.call_tool('inspect_topology', {'path': str(FIXTURE.resolve())})
                assert not graph.isError
                course = tmp_path / 'lessons'
                course.mkdir()
                report = await session.call_tool('verify_course',
                    {'path': str(FIXTURE.resolve()), 'lessons_path': str(course)})
                assert not report.isError
                assert json.loads(report.content[0].text)['coverage']['covered'] == 0
    asyncio.run(run())
    assert sorted(str(p.relative_to(FIXTURE)) for p in FIXTURE.rglob('*')) == before


def test_invalid_inventory_returns_input_error(tmp_path):
    (tmp_path / 'scan.json').write_text('{}')
    assert main(['verify', str(FIXTURE), '--out', str(tmp_path)]) == 2

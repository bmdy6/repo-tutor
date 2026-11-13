"""Read-only stdio MCP interface. No model calls and no artifact writes."""
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from repo_tutor.graph import topology
from repo_tutor.scanner import scan
from repo_tutor.verify import verify

server = FastMCP('repo-tutor')
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


@server.tool(annotations=READ_ONLY)
def scan_repository(path: str) -> dict:
    """Read local Python source and return an AST inventory; never execute target code."""
    return scan(path)


@server.tool(annotations=READ_ONLY)
def inspect_topology(path: str) -> dict:
    """Read source and return dependency-first components, cycles and static entry flows."""
    return topology(scan(path))


@server.tool(annotations=READ_ONLY)
def verify_course(path: str, lessons_path: str) -> dict:
    """Read local source and Markdown lessons; verify citations and coverage without writes."""
    directory = Path(lessons_path)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('lessons_path must be a real directory')
    lessons = {p.name: p.read_text() for p in sorted(directory.glob('*.md')) if not p.is_symlink()}
    return verify(path, scan(path), lessons)


def main():
    server.run(transport='stdio')


if __name__ == '__main__':
    main()

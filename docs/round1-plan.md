# Round 1 implementation plan

Goal: turn a Python repository into a dependency-ordered, source-linked onboarding course.
Architecture: AST scanner → resolved static graph → SCC dependency order → bounded model outline/lessons → deterministic verification. CLI owns writes; MCP exposes only local read-only analysis.
Stack: Python 3.11+, stdlib ast/urllib/tomllib, jsonschema, official MCP Python SDK, pytest.

## Constraints and decisions
- Clean-room implementation. Use only this empty repository, public documentation and the pinned public demo.
- Keep repository private. Bootstrap main once; all implementation on round1; open PR without merging.
- Never execute or import scanned code. Skip symlinks, common generated/test directories; report parse failures.
- Scan/graph/verify never call a model. Model requests capped, no automatic retries; persist request accounting before network calls.
- Facts require source coordinates and symbol labels. Verification establishes mechanical traceability, never semantic truth.
- Keep cycles as strongly connected components; dependency groups precede dependants. Unresolved dynamic calls stay unresolved.
- MCP tools scan_repository, inspect_topology, verify_course are read-only with readOnlyHint, destructiveHint=false, openWorldHint=false.

## Work and evidence
- [x] Scanner + JSON Schema: fixture includes src layout, relative imports, public/private symbols, CLI, routes, cycles and unresolved calls. Test inventory, exact coordinates, source hashes, malformed/symlink handling.
- [x] Graph: test dependency-first order, SCCs and entry reachability. Keep unresolved calls visible.
- [x] Generation: model only names deterministic lesson groups and writes prose from bounded numbered excerpts. Fake model tests for outline ownership, bad output, budget, citations and unsafe output paths.
- [x] Verification: validate citation file/range/symbol and source drift; coverage counts only lesson body citations, not outline or inventory. Report uncited prose and missing mermaid separately.
- [x] CLI + MCP: exercise scan/plan/write/verify/all with fake model and real MCP stdio initialize/list/call; no model tools exposed over MCP.
- [x] Demo: Flask 3.1.2, scan entire default production scope, generate full outline and 3 real sample lessons, verify both sample and complete course; cap real API attempts at 30.
- [ ] Delivery: run pytest/build, leak/path checks, README 3-command real smoke; commit/push round1, PR, observe CI green; report links/limitations/counts; create DONE-r1 last.

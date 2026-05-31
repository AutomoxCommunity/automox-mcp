# automox-mcp — project instructions

Repo-specific invariants for this MCP server. These are **self-enforcing reminders**: follow them without waiting to be asked. (General working preferences live in the user-global `~/.claude/CLAUDE.md`.)

## Adding / removing / renaming a tool

A tool's name and count appear in several hand-maintained places. When you change the tool set, update **all** of these in the same change — CI guards some, but not all:

| Location | What to update | CI-guarded? |
|---|---|---|
| `src/automox_mcp/tools/<domain>_tools.py` | the `@server.tool` registration | — |
| `src/automox_mcp/tools/meta_tools.py` `_DOMAIN_CATALOG` | the `(name, description)` entry (the model-facing discovery directory) | ✅ `test_doc_tool_counts.py` |
| `docs/tool-reference.md` | the bullet **and** its `## Domain (N tools)` section count **and** the top "all N tools" header | ✅ `test_doc_tool_counts.py` |
| `README.md` + `mcpb/manifest.json` | total / read / write counts | ✅ `test_doc_tool_counts.py` |
| `docs/api-coverage.md` | coverage map / omission rationale / build-backlog rows | ❌ **manual — easy to forget** |
| `tests/smoke_production.py` | live read-side coverage for new read tools (not destructive writes) | ❌ **manual, not in CI** |
| `CHANGELOG.md` | the entry under the active version | ❌ manual |

The current split is **130 tools / 84 read / 46 write**. `discover_capabilities` is intentionally excluded from `_DOMAIN_CATALOG`.

## Local gate before every push

A **pre-push git hook is the deterministic backstop**: `.pre-commit-config.yaml` runs the whole-repo gate at `pre-push`, so a push can't reach origin without passing it — no need to remember to run it by hand. After a fresh clone, activate it once:

```
uv run pre-commit install        # wires both pre-commit and pre-push hooks
```

The pre-push gate (and the manual equivalent) is:

```
uv run ruff format --check .     # NB: separate tool from `ruff check`
uv run ruff check .
uv run mypy .
uv run pytest --cov=automox_mcp --cov-fail-under=90
```

Coverage sits near the 90% floor — new branches (e.g. idempotency cache-hit / exception-release handlers on write tools) need their own tests or the floor breaks. `bandit` is configured but **manual/non-blocking** (has untriaged B104/B613 findings); run it with `uv run pre-commit run bandit --hook-stage manual --all-files`.

## Release safety

- **Never push a tag without an explicit go-ahead.** A `vX.Y.Z` tag push triggers irreversible PyPI / registry / MCPB publishing. Releasing = merge PR → tag-push (never the GitHub "Publish release" UI).
- Versions must match across `pyproject.toml`, `server.json` (incl. `packages[].version`), `mcpb/manifest.json` — the `manifests` CI job enforces this.
- Capability/destructive-gating policy lives in `docs/api-coverage.md`; read it before adding any write/delete tool to pick the right safety tier.

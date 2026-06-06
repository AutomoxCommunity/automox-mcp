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

The current split is **133 tools / 85 read / 48 write**. `discover_capabilities` is intentionally excluded from `_DOMAIN_CATALOG`.

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

Coverage sits near the 90% floor — new branches (e.g. idempotency cache-hit / exception-release handlers on write tools) need their own tests or the floor breaks. `bandit` (`-r src/ -c pyproject.toml`) runs at **pre-push and in the CI `lint` job**; existing findings are `# nosec`-justified inline (B104 bind-host string compares in `transport_security.py`; B613 sanitizer scan-target chars in `utils/sanitize.py`). A new bandit finding blocks the push and CI — `# nosec BXXX` it with a one-line reason only when genuinely safe.

## Testing conventions — fixtures must be real, smoke must assert correctness

Unit tests here stub the upstream via `StubClient`: you feed a canned response and assert on the request body. **A stub authored from the same wrong mental model as the code will agree with the code and pass while both are wrong** — this is exactly how three live-contract bugs shipped (#132: a search filter sent under the wrong body key, a saved-search body missing its `search` envelope, a packages list that truncates). Stub-based unit tests verify internal consistency, **not** conformance to the live API. So:

- **Wrapper unit-test fixtures must be captured (sanitized) real payloads, not invented shapes.** Before asserting "the wrapper sends body X / parses response Y", confirm X and Y against the live tenant (`tests/verify_reported_bugs.py` or an ad-hoc probe with `~/automox/.env`). A fixture like `{"data": [...], "total": N}` for an endpoint that actually returns a Spring `Page` (`content`/`total_elements`) tests fiction.
- **Smoke (`tests/smoke_production.py`) must assert correctness, not just "got a response".** `_safe_call` returns `None` on a tool error (caught → FAIL), but a tool that returns `200` with the *wrong* data passes any `resp is not None` check. For tools where wrong-but-200 is possible, assert a property that only holds when the call is correct: a filter *narrows* the result vs. unfiltered; an auto-paginated list reports `metadata.complete`; a write round-trips create→delete.
- Smoke is **manual and not in CI** — it only catches regressions if someone runs it. Gating it is tracked separately (see the smoke-in-CI issue / `docs/api-coverage.md`).

## Release safety

- **Never push a tag without an explicit go-ahead.** A `vX.Y.Z` tag push starts the publish run for irreversible PyPI / registry / MCPB publishing. Releasing = merge PR → tag-push (never the GitHub "Publish release" UI).
- **Run the smoke suite before tagging.** CI cannot — it has no live credentials by design (the tenant API key is never given to CI). The smoke suite is the only layer that exercises the real API, so it is a manual pre-tag gate: `set -a && . ~/automox/.env && set +a && uv run python tests/smoke_production.py` and confirm **0 failures** before pushing the tag. (This is how the #132 contract bugs would have been caught — the suite existed but nothing prompted a run.)
- **The publish run pauses for manual approval** — the `release` GitHub environment requires a reviewer (`ax-jkikta`). A tag push that "hangs" is waiting on that approval click, not broken; nothing publishes until it's approved. After publish, the `verify-publish` job installs the new version from PyPI and boots it.
- Versions must match across **four** files — the `manifests` CI job enforces all of them: `pyproject.toml`, `server.json` (incl. `packages[].version`), `mcpb/manifest.json`, and `mcpb/pyproject.toml` (**both** its `version` *and* the `automox-mcp>=` dependency floor). Missing the last file is an easy mistake — the job rewrites these from the tag at publish, but they must already be in sync on `main`.
- Capability/destructive-gating policy lives in `docs/api-coverage.md`; read it before adding any write/delete tool to pick the right safety tier.

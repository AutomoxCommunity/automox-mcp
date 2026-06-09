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

## Adding / removing an MCP resource or MCP App

Resources (incl. `ui://` MCP App UIs) and the Apps extension have their own hand-maintained surfaces — and unlike tools, **none of them are CI-guarded**:

| Location | What to update | CI-guarded? |
|---|---|---|
| `src/automox_mcp/resources/<name>_resources.py` + `resources/__init__.py` | the `@server.resource` registration + its `register_*` call | — |
| `docs/tool-reference.md` + `mcpb/manifest.json` | the **"N MCP resources"** count | ✅ `test_doc_tool_counts.py` |
| `docs/tool-reference.md` `## MCP Resources` | the resource-table **row** and (for Apps) the `### MCP Apps` note | ❌ **manual — easy to forget** |
| `CHANGELOG.md` | the entry under the active version | ❌ manual |

The **"N MCP resources"** count in `docs/tool-reference.md` and `mcpb/manifest.json` is now **CI-guarded** by `tests/test_doc_tool_counts.py` (real-FastMCP resource introspection, mirroring the tool guard). ⚠️ The resource-table **row** and the `### MCP Apps` note are still **manual** — a new resource added without its row/note ships silently. There are currently **14** resources (9 reference + 5 `ui://` MCP App UIs).

## Advertising `output_schema` (demand-driven, not blanket)

Advertise `output_schema` on a read tool only when it becomes a **render target** — an App/UI surface, a schema-aware host that validates output, or the model needing the typed shape to chain calls. Do **not** speculatively schematize the read surface: `maybe_format_markdown` already emits `structuredContent` (issue #177), so un-schematized read tools are fully consumable. A blanket schema is either dead weight (a permissive shape that documents nothing) or — across heterogeneous tools — an unverifiable contract: FastMCP **validates returns against the schema at runtime**, smoke isn't in CI, and a too-strict schema that drifts from the live payload fails the tool in production (cf. the #132 live-contract bugs). When you do add one, it must validate the **real** `structuredContent` payload, smoke-verified, and the model must be permissive (all-optional, `dict[str, Any]` for variable sub-objects, never `extra="forbid"`). Rationale and the per-tool decisions live in `docs/api-coverage.md`.

MCP Apps specifics: an App is a `ui://` HTML resource (FastMCP auto-resolves the `text/html;profile=mcp-app` MIME) plus an `app=AppConfig(...)` on the entry tool's `@server.tool` (top-level `FastMCP.tool` accepts `app=`; the lower-level provider decorator does not). Keep App UIs **self-contained** (inline JS/CSS, no CDN imports) so they run under the host's default deny-all CSP with no `ResourceCSP` domains. `prefab_ui` is not installed — do not use `PrefabAppConfig`/`@app.ui()`.

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

## `docs/release-notes.md` — customer-facing feature highlights

`docs/release-notes.md` is a curated list of notable **features and capabilities**. Its **primary purpose is to inform customers** of what's new; **secondarily** it serves as source material for go-to-market (GTM) content. It is intentionally **not** a comprehensive record of changes — that is the role of `CHANGELOG.md`, which remains the authoritative, complete log of every change (features, fixes, security, and internal work). Highlights link to `CHANGELOG.md` for full detail rather than reproducing it.

When adding a highlight:

- **Scope is features and capabilities.** Bug fixes, dependency updates, security patches, and internal/CI work are recorded in `CHANGELOG.md`, not here. A release earns a highlight only when it introduces or meaningfully expands a customer-visible capability.
- **Audience is customers first (GTM second).** Write benefit-first and in the present tense — what an operator can now do and why it matters.
- **No internal references** (issue/PR numbers, file or symbol names, internal tooling) and **no tenant- or customer-specific data** (live device counts, query results, org names/IDs). Cite performance figures only as a qualified ballpark ("in testing").
- **Product-capability counts are in scope** as point-in-time facts — tool/resource counts, API-coverage % — and should be stated where the number is part of the story (a launch count, a capability expansion). The version + date heading anchors them, so they read as "as of this release," not a standing current-capability claim. These are distinct from the tenant-specific counts above. Use only counts the `CHANGELOG.md` states cleanly; if it is ambiguous or self-contradictory for a release (e.g. a folded entry, or two entries disagreeing), omit the number rather than guess.
- **Security details and the full change history live in `CHANGELOG.md` and security advisories**, not here.
- **Entry shape:** a bold headline + 1–3 sentences of value, an optional `Caveat:` (host requirement, support scope) and an optional `Upgrade:` (operator action for a breaking change), tagged `[Feature]` or `[Improvement]`.

On each release, after the `CHANGELOG.md` entry: if the release introduces a notable feature or capability, add a highlight at the top of `docs/release-notes.md`; otherwise it stays in `CHANGELOG.md` only.

# Contributing

Thanks for your interest in `automox-mcp`. This project is the official Automox Model Context Protocol (MCP) server. We welcome external contributions — issues, bug reports, documentation fixes, and new tools or workflows.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ground rules

* **Open an issue before large changes.** Quick fixes (typos, obvious bugs, missing annotations) can go straight to a PR. For new tools, new workflows, or anything that changes externally visible behavior, file an issue first so we can align on scope and avoid wasted work.
* **Don't include credentials.** Never commit real API keys, account UUIDs, org IDs, device IDs, or customer data. The `.env.example` file enumerates the variables we expect; real values live in your local `.env` (gitignored) or in `~/automox/.env`.
* **Security issues go through `SECURITY.md`.** Don't file vulnerabilities as public GitHub issues — see [`SECURITY.md`](SECURITY.md) for the private disclosure path.

## Development setup

```bash
git clone https://github.com/AutomoxCommunity/automox-mcp.git
cd automox-mcp
uv python install
uv sync --python 3.13 --dev
```

Run the server against MCP Inspector for interactive debugging:

```bash
fastmcp dev
```

## Running checks locally

Run the same checks CI runs before pushing:

```bash
uv run --python 3.13 ruff check .
uv run --python 3.13 mypy .
uv run --python 3.13 pytest
```

We target ≥90% line coverage. New tools and workflows are expected to ship with tests.

Optional but encouraged:

```bash
uv run --python 3.13 bandit -r src/
```

## Adding a new tool

1. Add the implementation under `src/automox_mcp/tools/<domain>_tools.py`, registering it via `@server.tool(...)` in the module's `register()` function.
2. **Always include MCP tool annotations**: `readOnlyHint`, `destructiveHint`, `idempotentHint`, and `openWorldHint`. Write tools (anything that mutates state in Automox) must set `destructiveHint=True`; read-only tools must set `readOnlyHint=True`.
3. Keep the description narrow and behavior-accurate. Don't over-promise. Reviewers and LLM hosts use the description verbatim — vague or aspirational language causes wrong tool selection.
4. Add unit tests under `tests/`. Mock the HTTP layer; do not hit the real Automox API in CI.
5. Update [`docs/tool-reference.md`](docs/tool-reference.md) and bump the tool counts in `mcpb/manifest.json`'s `long_description` and the `README.md` summary if your change crosses a count boundary.

## Pull request checklist

Before opening a PR:

- [ ] `ruff check .` clean
- [ ] `mypy .` clean
- [ ] `pytest` green, coverage ≥90%
- [ ] Tool annotations present on any new `@server.tool(...)` registration
- [ ] `docs/tool-reference.md` updated if tools/domains changed
- [ ] `CHANGELOG.md` entry under the next version
- [ ] `pyproject.toml` `version` bumped if this PR is a release

## Releases

Releases are driven by Git tags. The release workflow validates that the tag matches `pyproject.toml`'s `version` and publishes to PyPI plus the MCP registry. Do not publish manually.

## License

By contributing, you agree that your contributions will be licensed under the project's MIT License (see [`LICENSE`](LICENSE)).

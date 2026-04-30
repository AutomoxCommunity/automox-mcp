# Automox MCPB Bundle

This directory contains the [MCPB (MCP Bundle)](https://github.com/modelcontextprotocol/mcpb) Desktop Extension wrapper for the Automox MCP server.

The bundle is a thin shim: `manifest.json` + `pyproject.toml` + a one-file Python entry point. When Claude Desktop installs the `.mcpb` archive, it runs `uv` against this directory, which installs `automox-mcp` from PyPI and starts the server. No source code is bundled — every install pulls the latest pinned version from PyPI.

## Local development

```bash
# Install the MCPB CLI (one-time)
npm install -g @anthropic-ai/mcpb

# Validate the manifest
mcpb validate manifest.json

# Build the bundle archive (produces ./automox-mcp.mcpb)
mcpb pack .
```

The CI release workflow builds the `.mcpb` automatically on every `v*` tag and uploads it as a GitHub Release asset. End users do **not** build from this directory.

## Updating

The version in `manifest.json` and `pyproject.toml` is overridden at build time by the release workflow to match the git tag, so contributors editing this directory should not have to keep both files in lockstep.

## What's in the bundle at install time

After `mcpb pack`, the `.mcpb` archive contains:

- `manifest.json` — bundle metadata, user_config schema, env-var mapping
- `icon.png` — 256×256 RGBA Automox logo
- `pyproject.toml` — declares `automox-mcp>=<version>` as the only dependency
- `server/main.py` — one-line shim that imports and calls `automox_mcp.main()`

Files matched by `.mcpbignore` are excluded from the archive.

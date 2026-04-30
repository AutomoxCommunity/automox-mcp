"""Entry point for the Automox MCP Bundle.

This is a thin shim. The real implementation lives in the `automox-mcp`
PyPI package, declared as a dependency in `mcpb/pyproject.toml`. When
Claude Desktop launches this bundle, it runs `uv run` against this
directory, which installs `automox-mcp` from PyPI and then executes
this file's `main()` entry point.
"""

from automox_mcp import main

if __name__ == "__main__":
    main()

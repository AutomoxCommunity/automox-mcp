"""Regenerate the ``tools`` and ``prompts`` arrays in ``mcpb/manifest.json``.

Claude Desktop's extension-details view renders its "Tools" and "Prompts"
sections from these manifest arrays. They are *generated, not hand-written*:
tool names come from the actually-registered server (all gates on, matching
the "N tools" headline) and descriptions from the ``discover_capabilities``
domain catalog, so the listing can't drift from the model-facing surface.
``tests/test_doc_tool_counts.py`` guards the result in CI — when the tool or
prompt set changes, re-run this script:

    uv run python scripts/generate_mcpb_catalog.py

Prompt ``text`` is the prompt's description (the MCPB schema requires a text
field, but the real prompt body is rendered server-side per-arguments at
runtime, so the description is the only static truth worth shipping).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MANIFEST = _REPO_ROOT / "mcpb" / "manifest.json"

# discover_capabilities is intentionally absent from the domain catalog
# (it doesn't self-list), so its display description lives here.
_META_TOOL_DESCRIPTIONS = {
    "discover_capabilities": (
        "Canonical inventory of the server's tools by domain, with live per-session availability"
    ),
}

# The full-gates configuration: every opt-in gated tool registers, matching
# the documented headline count (mirrors tests/test_doc_tool_counts.py).
_FULL_GATES = {
    "AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS": "true",
    "AUTOMOX_MCP_ALLOW_SPLASHTOP_BULK_INSTALL_UNINSTALL": "true",
    "AUTOMOX_MCP_ALLOW_DELETE_DEVICE": "true",
    "AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE": "true",
    "AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS": tempfile.gettempdir(),
}

_GATING_ENV = (
    "AUTOMOX_MCP_READ_ONLY",
    "AUTOMOX_MCP_TRANSPORT",
    "AUTOMOX_MCP_MODULES",
    "AUTOMOX_MCP_TOOL_PREFIX",
    *_FULL_GATES,
)


class _NullClient:
    """Registration-time stand-in; tool modules only use the client at call time."""

    org_id = 0
    org_uuid = ""
    account_uuid = ""


def build_tool_entries() -> list[dict[str, str]]:
    from fastmcp import FastMCP

    from automox_mcp.tools import _get_tool_names, register_tools
    from automox_mcp.tools.meta_tools import _DOMAIN_CATALOG

    server = FastMCP("mcpb-catalog")
    register_tools(server, client=_NullClient())  # type: ignore[arg-type]
    registered = _get_tool_names(server)

    descriptions: dict[str, str] = dict(_META_TOOL_DESCRIPTIONS)
    for tools in _DOMAIN_CATALOG.values():
        for name, desc in tools:
            descriptions.setdefault(name, desc)  # first occurrence wins

    missing = registered - descriptions.keys()
    if missing:
        raise SystemExit(f"registered tools missing a catalog description: {sorted(missing)}")
    phantom = descriptions.keys() - registered
    if phantom:
        raise SystemExit(f"catalog lists unregistered tools: {sorted(phantom)}")

    return [{"name": name, "description": descriptions[name]} for name in sorted(registered)]


def build_prompt_entries() -> list[dict[str, Any]]:
    from fastmcp import FastMCP

    from automox_mcp.prompts import register_prompts

    server = FastMCP("mcpb-catalog-prompts")
    register_prompts(server)
    entries: list[dict[str, Any]] = []
    for key, comp in server.local_provider._components.items():
        if not key.startswith("prompt:"):
            continue
        entry: dict[str, Any] = {
            "name": comp.name,
            "description": comp.description,
            "text": comp.description,
        }
        arguments = [a.name for a in (getattr(comp, "arguments", None) or [])]
        if arguments:
            entry["arguments"] = arguments
        entries.append(entry)
    return sorted(entries, key=lambda e: str(e["name"]))


def main() -> None:
    for key in _GATING_ENV:
        os.environ.pop(key, None)
    os.environ.update(_FULL_GATES)

    manifest = json.loads(_MANIFEST.read_text())
    tools = build_tool_entries()
    prompts = build_prompt_entries()

    # Rebuild preserving key order: each array sits beside its *_generated
    # flag, and the flags become false — everything is listed, nothing extra
    # is generated at runtime.
    rebuilt: dict[str, Any] = {}
    for key, value in manifest.items():
        if key == "tools_generated":
            rebuilt["tools"] = tools
            rebuilt["tools_generated"] = False
        elif key == "prompts_generated":
            rebuilt["prompts"] = prompts
            rebuilt["prompts_generated"] = False
        elif key in ("tools", "prompts"):
            continue  # re-inserted beside their flags above
        else:
            rebuilt[key] = value

    _MANIFEST.write_text(json.dumps(rebuilt, indent=2) + "\n")
    print(f"wrote {len(tools)} tools and {len(prompts)} prompts to {_MANIFEST}")


if __name__ == "__main__":
    main()

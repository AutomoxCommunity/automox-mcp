"""Tool registration modules for Automox MCP."""

from __future__ import annotations

import importlib
import logging

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..client import AutomoxClient
from ..utils.tooling import get_enabled_modules, get_tool_prefix, is_read_only

logger = logging.getLogger(__name__)

# Tokens that should not be naively title-cased when deriving a human-readable
# tool title from its snake_case name.
_TITLE_ACRONYMS = {
    "api": "API",
    "uuid": "UUID",
    "ocsf": "OCSF",
    "rbac": "RBAC",
    "v2": "v2",
}
# Joiner words kept lowercase when not the first word of the title.
_TITLE_LOWERCASE = {"to", "for", "by", "from", "of"}

# Map of module name -> (register_function_module, contains_write_tools)
_MODULE_REGISTRY: dict[str, tuple[str, bool]] = {
    "audit": ("audit_tools", False),
    "audit_v2": ("audit_v2_tools", False),
    "devices": ("device_tools", True),
    "device_search": ("device_search_tools", False),
    "policies": ("policy_tools", True),
    "policy_history": ("policy_history_tools", False),
    "users": ("account_tools", True),
    "groups": ("group_tools", True),
    "events": ("event_tools", False),
    "reports": ("report_tools", False),
    "packages": ("package_tools", False),
    "webhooks": ("webhook_tools", True),
    "worklets": ("worklet_tools", False),
    "data_extracts": ("data_extract_tools", True),
    "vuln_sync": ("vuln_sync_tools", True),
    "compound": ("compound_tools", False),
    "policy_windows": ("policy_windows_tools", True),
    "splashtop": ("splashtop_tools", True),
}

# Modules that always load regardless of AUTOMOX_MCP_MODULES filtering
_ALWAYS_LOAD: dict[str, tuple[str, bool]] = {
    "meta": ("meta_tools", False),
}


def register_tools(server: FastMCP, *, client: AutomoxClient) -> None:
    """Register Automox tool modules with the FastMCP server.

    Respects ``AUTOMOX_MCP_MODULES`` for selective loading and
    ``AUTOMOX_MCP_READ_ONLY`` to skip write-capable modules.
    """
    enabled = get_enabled_modules()
    read_only = is_read_only()

    all_modules = {**_MODULE_REGISTRY, **_ALWAYS_LOAD}

    for module_name, (tool_module_name, _) in all_modules.items():
        # Skip modules not in the enabled set (unless always-load)
        if enabled is not None and module_name not in enabled and module_name not in _ALWAYS_LOAD:
            logger.info("Skipping module %s (not in AUTOMOX_MCP_MODULES)", module_name)
            continue

        try:
            mod = importlib.import_module(f".{tool_module_name}", __package__)
            register_fn = mod.register
            register_fn(server, read_only=read_only, client=client)
        except ImportError:
            logger.warning("Tool module %s not found, skipping", tool_module_name)
        except Exception:
            logger.exception("Failed to register tool module %s", tool_module_name)

    # Populate human-readable titles before any prefixing (titles derive from the
    # unprefixed name).
    _apply_tool_titles(server)

    # Apply tool name prefix if configured
    prefix = get_tool_prefix()
    if prefix:
        _apply_tool_prefix(server, prefix)


def _humanize_tool_name(name: str) -> str:
    """Derive a human-readable title from a snake_case tool name.

    ``list_account_rbac_roles`` -> ``List Account RBAC Roles``;
    ``get_device_by_uuid`` -> ``Get Device by UUID``.
    """
    words = name.split("_")
    titled: list[str] = []
    for i, word in enumerate(words):
        if word in _TITLE_ACRONYMS:
            titled.append(_TITLE_ACRONYMS[word])
        elif i != 0 and word in _TITLE_LOWERCASE:
            titled.append(word)
        else:
            titled.append(word.capitalize())
    return " ".join(titled)


def _apply_tool_titles(server: FastMCP) -> None:
    """Populate ``annotations.title`` for every tool that lacks one.

    Titles are derived from the tool name so they cannot drift from a separate
    source of truth. An explicitly-set title is preserved. Applied as a
    post-registration pass (mirroring ``_apply_tool_prefix``) so it covers every
    tool module without touching each ``@server.tool`` registration.
    """
    lp = getattr(server, "local_provider", None)
    if lp is None:  # lightweight test stubs without FastMCP internals
        return
    for key, comp in list(lp._components.items()):
        if not key.startswith("tool:"):
            continue
        title = _humanize_tool_name(comp.name)
        ann = comp.annotations
        if ann is None:
            renamed = comp.model_copy(update={"annotations": ToolAnnotations(title=title)})
            lp._components[key] = renamed
        elif not ann.title:
            ann.title = title


def _get_tool_names(server: FastMCP) -> set[str]:
    """Return the set of registered tool names on *server*."""
    lp = server.local_provider
    return {comp.name for key, comp in lp._components.items() if key.startswith("tool:")}


def _apply_tool_prefix(server: FastMCP, prefix: str) -> None:
    """Rename all registered tools with a prefix to prevent cross-server collisions.

    Uses FastMCP internal API (``local_provider._components``).
    """
    lp = server.local_provider
    tool_keys = [k for k in lp._components if k.startswith("tool:")]
    for key in tool_keys:
        tool = lp._components.pop(key)
        renamed = tool.model_copy(update={"name": f"{prefix}_{tool.name}"})
        lp._add_component(renamed)
    logger.info(
        "Applied tool prefix '%s' to %d tools",
        prefix,
        len(tool_keys),
    )


__all__ = ["register_tools", "_get_tool_names"]

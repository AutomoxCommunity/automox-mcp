"""Tool registration modules for Automox MCP."""

from __future__ import annotations

import importlib
import logging

from fastmcp import FastMCP

from ..client import AutomoxClient
from ..utils.tooling import get_enabled_modules, get_tool_prefix, is_read_only

logger = logging.getLogger(__name__)

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

    # Apply tool name prefix if configured
    prefix = get_tool_prefix()
    if prefix:
        _apply_tool_prefix(server, prefix)


def _get_tool_names(server: FastMCP) -> set[str]:
    """Return the set of registered tool names on *server*."""
    lp = server.local_provider
    return {
        comp.name
        for key, comp in lp._components.items()
        if key.startswith("tool:")
    }


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

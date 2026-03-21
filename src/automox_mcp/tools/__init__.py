"""Tool registration modules for Automox MCP."""

from __future__ import annotations

import importlib
import logging

from fastmcp import FastMCP

from ..client import AutomoxClient
from ..utils.tooling import get_enabled_modules, is_read_only

logger = logging.getLogger(__name__)

# Map of module name -> (register_function_module, contains_write_tools)
_MODULE_REGISTRY: dict[str, tuple[str, bool]] = {
    "audit": ("audit_tools", False),
    "devices": ("device_tools", True),
    "policies": ("policy_tools", True),
    "users": ("account_tools", True),
    "groups": ("group_tools", True),
    "events": ("event_tools", False),
    "reports": ("report_tools", False),
    "packages": ("package_tools", False),
    "webhooks": ("webhook_tools", True),
    "compound": ("compound_tools", False),
}


def register_tools(server: FastMCP, *, client: AutomoxClient) -> None:
    """Register Automox tool modules with the FastMCP server.

    Respects ``AUTOMOX_MCP_MODULES`` for selective loading and
    ``AUTOMOX_MCP_READ_ONLY`` to skip write-capable modules.
    """
    enabled = get_enabled_modules()
    read_only = is_read_only()

    for module_name, (tool_module_name, _has_writes) in _MODULE_REGISTRY.items():
        # Skip modules not in the enabled set (if filtering is active)
        if enabled is not None and module_name not in enabled:
            logger.info("Skipping module %s (not in AUTOMOX_MCP_MODULES)", module_name)
            continue

        try:
            mod = importlib.import_module(f".{tool_module_name}", __package__)
            register_fn = getattr(mod, "register")
            register_fn(server, read_only=read_only, client=client)
        except ImportError:
            logger.warning("Tool module %s not found, skipping", tool_module_name)
        except Exception:
            logger.exception("Failed to register tool module %s", tool_module_name)


__all__ = ["register_tools"]

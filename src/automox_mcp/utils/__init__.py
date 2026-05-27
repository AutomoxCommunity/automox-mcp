"""Shared utility helpers for the Automox MCP server."""

from __future__ import annotations

from .organization import resolve_org_uuid
from .response import (
    build_pagination_metadata,
    build_section_summary,
    build_section_summary_notes,
    extract_list,
    normalize_status,
    require_org_id,
)
from .tooling import (
    RateLimiter,
    RateLimitError,
    as_tool_response,
    call_tool_workflow,
    enforce_rate_limit,
    format_error,
    get_enabled_modules,
    is_read_only,
)

__all__ = [
    "RateLimitError",
    "RateLimiter",
    "as_tool_response",
    "build_pagination_metadata",
    "build_section_summary",
    "build_section_summary_notes",
    "call_tool_workflow",
    "enforce_rate_limit",
    "extract_list",
    "format_error",
    "get_enabled_modules",
    "is_read_only",
    "normalize_status",
    "require_org_id",
    "resolve_org_uuid",
]

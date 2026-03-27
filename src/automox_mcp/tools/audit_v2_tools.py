"""Audit Service v2 (OCSF) tools for Automox MCP."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from ..client import AutomoxAPIError, AutomoxClient
from ..utils.tooling import (
    RateLimitError,
    as_tool_response,
    enforce_rate_limit,
    format_error,
    maybe_format_markdown,
)
from ..workflows.audit_v2 import audit_events_ocsf as _audit_events_ocsf

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register audit service v2 (OCSF) tools."""

    async def _call_workflow(
        func: Callable[..., Awaitable[dict[str, Any]]],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            await enforce_rate_limit()
            kwargs.setdefault("org_id", client.org_id)
            if kwargs.get("org_id") is None:
                raise ToolError("org_id required - set AUTOMOX_ORG_ID or pass org_id explicitly.")
            result: dict[str, Any] = await func(client, **kwargs)
        except (ValidationError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        except RateLimitError as exc:
            raise ToolError(str(exc)) from exc
        except AutomoxAPIError as exc:
            raise ToolError(format_error(exc)) from exc
        except ToolError:
            raise
        except Exception as exc:
            logger.exception("Unexpected error in tool call")
            raise ToolError("An internal error occurred. Check server logs for details.") from exc
        return as_tool_response(result)

    @server.tool(
        name="audit_events_ocsf",
        description=(
            "Query OCSF-formatted audit events from the Automox Audit Service v2. "
            "Supports filtering by date, event category (authentication, account_change, "
            "entity_management, user_access, web_resource_activity), and event type name. "
            "Uses cursor-based pagination for large result sets."
        ),
    )
    async def audit_events_ocsf(
        date: str,
        category_name: str | None = None,
        type_name: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await _call_workflow(
            _audit_events_ocsf,
            {
                "date": date,
                "category_name": category_name,
                "type_name": type_name,
                "cursor": cursor,
                "limit": limit,
            },
        )
        return maybe_format_markdown(result, output_format)


__all__ = ["register"]

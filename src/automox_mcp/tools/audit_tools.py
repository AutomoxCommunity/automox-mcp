"""Audit trail tools for Automox MCP."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from .. import workflows
from ..client import AutomoxAPIError, AutomoxClient
from ..schemas import AuditTrailEventsParams, OrgIdContextMixin, OrgIdRequiredMixin
from ..utils.tooling import (
    RateLimitError,
    as_tool_response,
    enforce_rate_limit,
    format_error,
)


def register(server: FastMCP) -> None:
    """Register audit trail-related tools."""

    async def _call(
        func: Callable[..., Awaitable[dict[str, Any]]],
        params_model: type[BaseModel],
        raw_params: dict[str, Any],
        api: str | None = None,
    ) -> dict[str, Any]:
        try:
            await enforce_rate_limit(api)
            client = AutomoxClient(default_api=api)
            client_org_id = getattr(client, "org_id", None)
            async with client as session:
                params = dict(raw_params)
                if issubclass(params_model, (OrgIdContextMixin, OrgIdRequiredMixin)):
                    params.setdefault("org_id", client_org_id)
                    if params.get("org_id") is None:
                        raise ToolError(
                            "org_id required - set AUTOMOX_ORG_ID or pass org_id explicitly."
                        )
                model = params_model(**params)
                payload = model.model_dump(mode="python", exclude_none=True)
                if isinstance(model, (OrgIdContextMixin, OrgIdRequiredMixin)):
                    payload["org_id"] = model.org_id
                result: dict[str, Any] = await func(session, **payload)
        except (ValidationError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        except RateLimitError as exc:
            raise ToolError(str(exc)) from exc
        except AutomoxAPIError as exc:
            raise ToolError(format_error(exc)) from exc
        return as_tool_response(result)

    @server.tool(
        name="audit_trail_user_activity",
        description="Retrieve Automox audit trail events performed by a user on a specific date.",
    )
    async def audit_trail_user_activity(
        date: str,
        actor_email: str | None = None,
        actor_uuid: str | None = None,
        actor_name: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        include_raw_events: bool | None = False,
        org_uuid: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "date": date,
            "actor_email": actor_email,
            "actor_uuid": actor_uuid,
            "actor_name": actor_name,
            "cursor": cursor,
            "limit": limit,
            "include_raw_events": include_raw_events,
            "org_uuid": org_uuid,
        }
        return await _call(
            workflows.audit_trail_user_activity,
            AuditTrailEventsParams,
            params,
            api="console",
        )


__all__ = ["register"]

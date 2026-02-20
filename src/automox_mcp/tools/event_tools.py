"""Event-related tools for Automox MCP."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from .. import workflows
from ..client import AutomoxAPIError, AutomoxClient
from ..schemas import (
    GetEventsParams,
    OrgIdContextMixin,
    OrgIdRequiredMixin,
)
from ..utils.tooling import (
    RateLimitError,
    as_tool_response,
    enforce_rate_limit,
    format_error,
)


def register(server: FastMCP, *, read_only: bool = False) -> None:
    """Register event-related tools."""

    async def _call(
        func: Callable[..., Awaitable[dict[str, Any]]],
        params_model: type[BaseModel],
        raw_params: dict[str, Any],
        api: str | None = None,
        *,
        inject_org_id: bool = False,
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
                elif inject_org_id:
                    if client_org_id is None:
                        raise ToolError(
                            "org_id required - set AUTOMOX_ORG_ID or pass org_id explicitly."
                        )
                    payload["org_id"] = client_org_id
                result: dict[str, Any] = await func(session, **payload)
        except (ValidationError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        except RateLimitError as exc:
            raise ToolError(str(exc)) from exc
        except AutomoxAPIError as exc:
            raise ToolError(format_error(exc)) from exc
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"Unexpected error: {type(exc).__name__}: {exc}") from exc
        return as_tool_response(result)

    @server.tool(
        name="list_events",
        description=(
            "List Automox organization events with optional filters by policy, "
            "device, user, event name, or date range."
        ),
    )
    async def list_events(
        page: int | None = None,
        limit: int | None = None,
        count_only: bool | None = None,
        policy_id: int | None = None,
        server_id: int | None = None,
        user_id: int | None = None,
        event_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "page": page,
            "limit": limit,
            "count_only": count_only,
            "policy_id": policy_id,
            "server_id": server_id,
            "user_id": user_id,
            "event_name": event_name,
            "start_date": start_date,
            "end_date": end_date,
        }
        return await _call(
            workflows.list_events,
            GetEventsParams,
            params,
            api="console",
            inject_org_id=True,
        )


__all__ = ["register"]

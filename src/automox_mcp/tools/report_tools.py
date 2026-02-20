"""Report-related tools for Automox MCP."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from .. import workflows
from ..client import AutomoxAPIError, AutomoxClient
from ..schemas import (
    GetNeedsAttentionReportParams,
    GetPrepatchReportParams,
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
    """Register report-related tools."""

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
        name="prepatch_report",
        description=(
            "Retrieve the Automox pre-patch readiness report showing devices "
            "with pending patches before the next scheduled patch window."
        ),
    )
    async def prepatch_report(
        group_id: int | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        params = {
            "group_id": group_id,
            "limit": limit,
            "offset": offset,
        }
        return await _call(
            workflows.get_prepatch_report,
            GetPrepatchReportParams,
            params,
            api="console",
            inject_org_id=True,
        )

    @server.tool(
        name="noncompliant_report",
        description=(
            "Retrieve the Automox non-compliant devices report showing devices "
            "that need attention due to policy failures or missing patches."
        ),
    )
    async def noncompliant_report(
        group_id: int | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        params = {
            "group_id": group_id,
            "limit": limit,
            "offset": offset,
        }
        return await _call(
            workflows.get_noncompliant_report,
            GetNeedsAttentionReportParams,
            params,
            api="console",
            inject_org_id=True,
        )


__all__ = ["register"]

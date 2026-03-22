"""Report-related tools for Automox MCP."""

from __future__ import annotations

import logging

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
    maybe_format_markdown,
    format_error,
)


logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register report-related tools."""

    async def _call(
        func: Callable[..., Awaitable[dict[str, Any]]],
        params_model: type[BaseModel],
        raw_params: dict[str, Any],
        *,
        inject_org_id: bool = False,
    ) -> dict[str, Any]:
        try:
            await enforce_rate_limit()
            client_org_id = client.org_id
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
            result: dict[str, Any] = await func(client, **payload)
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
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "group_id": group_id,
            "limit": limit,
            "offset": offset,
        }
        result = await _call(
            workflows.get_prepatch_report,
            GetPrepatchReportParams,
            params,
            inject_org_id=True,
        )

        return maybe_format_markdown(result, output_format)

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
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "group_id": group_id,
            "limit": limit,
            "offset": offset,
        }
        result = await _call(
            workflows.get_noncompliant_report,
            GetNeedsAttentionReportParams,
            params,
            inject_org_id=True,
        )

        return maybe_format_markdown(result, output_format)


__all__ = ["register"]

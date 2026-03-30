"""Worklet catalog tools for Automox MCP."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from ..client import AutomoxAPIError, AutomoxClient
from ..schemas import (
    GetWisItemParams,
    OrgIdContextMixin,
    OrgIdRequiredMixin,
    SearchWisParams,
)
from ..utils.tooling import (
    RateLimitError,
    as_tool_response,
    enforce_rate_limit,
    format_error,
    format_validation_error,
    maybe_format_markdown,
)
from ..workflows.worklets import get_worklet_detail as _get_worklet_detail
from ..workflows.worklets import search_worklet_catalog as _search_worklet_catalog

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register worklet catalog tools."""

    async def _call(
        func: Callable[..., Awaitable[dict[str, Any]]],
        params_model: type[BaseModel],
        raw_params: dict[str, Any],
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
            result: dict[str, Any] = await func(client, **payload)
        except (ValidationError, ValueError) as exc:
            raise ToolError(format_validation_error(exc)) from exc
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
        name="search_worklet_catalog",
        description=(
            "Search the Automox community worklet catalog. "
            "Returns worklet names, descriptions, categories, and OS compatibility. "
            "Use to discover pre-built evaluation and remediation scripts."
        ),
    )
    async def search_worklet_catalog(
        query: str | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {"query": query}
        result = await _call(
            _search_worklet_catalog,
            SearchWisParams,
            params,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_worklet_detail",
        description=(
            "Get detailed information for a specific community worklet, "
            "including evaluation code, remediation code, and requirements."
        ),
    )
    async def get_worklet_detail(
        item_id: str,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {"item_id": item_id}
        result = await _call(
            _get_worklet_detail,
            GetWisItemParams,
            params,
        )
        return maybe_format_markdown(result, output_format)


__all__ = ["register"]

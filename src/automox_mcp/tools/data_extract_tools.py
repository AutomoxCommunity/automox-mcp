"""Data extract tools for Automox MCP."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from ..client import AutomoxAPIError, AutomoxClient
from ..schemas import (
    CreateDataExtractParams,
    GetDataExtractParams,
    ListDataExtractsParams,
    OrgIdContextMixin,
    OrgIdRequiredMixin,
)
from ..utils.tooling import (
    RateLimitError,
    as_tool_response,
    check_idempotency,
    enforce_rate_limit,
    format_error,
    format_validation_error,
    maybe_format_markdown,
    store_idempotency,
)
from ..workflows.data_extracts import (
    create_data_extract as _create_data_extract,
)
from ..workflows.data_extracts import (
    get_data_extract as _get_data_extract,
)
from ..workflows.data_extracts import (
    list_data_extracts as _list_data_extracts,
)

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register data extract tools."""

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
        name="list_data_extracts",
        description=(
            "List available data extracts for the Automox organization. "
            "Returns extract names, statuses, and download information."
        ),
    )
    async def list_data_extracts(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await _call(
            _list_data_extracts,
            ListDataExtractsParams,
            {},
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_data_extract",
        description=("Get details and download information for a specific data extract."),
    )
    async def get_data_extract(
        extract_id: str,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await _call(
            _get_data_extract,
            GetDataExtractParams,
            {"extract_id": extract_id},
        )
        return maybe_format_markdown(result, output_format)

    if not read_only:

        @server.tool(
            name="create_data_extract",
            description=(
                "Request a new data extract for bulk reporting. "
                "Returns the extract ID and initial status."
            ),
        )
        async def create_data_extract(
            extract_data: dict[str, Any],
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "create_data_extract")
            if cached is not None:
                return cached
            result = await _call(
                _create_data_extract,
                CreateDataExtractParams,
                {"extract_data": extract_data},
            )
            await store_idempotency(request_id, "create_data_extract", result)
            return result


__all__ = ["register"]

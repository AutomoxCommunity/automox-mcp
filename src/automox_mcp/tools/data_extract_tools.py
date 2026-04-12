"""Data extract tools for Automox MCP."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from ..client import AutomoxClient
from ..schemas import (
    CreateDataExtractParams,
    GetDataExtractParams,
    ListDataExtractsParams,
)
from ..utils.tooling import (
    call_tool_workflow,
    check_idempotency,
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

    @server.tool(
        name="list_data_extracts",
        description=(
            "List available data extracts for the Automox organization. "
            "Returns extract names, statuses, and download information."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def list_data_extracts(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            _list_data_extracts,
            {},
            params_model=ListDataExtractsParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_data_extract",
        description=("Get details and download information for a specific data extract."),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_data_extract(
        extract_id: str,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            _get_data_extract,
            {"extract_id": extract_id},
            params_model=GetDataExtractParams,
        )
        return maybe_format_markdown(result, output_format)

    if not read_only:

        @server.tool(
            name="create_data_extract",
            description=(
                "Request a new data extract for bulk reporting. "
                "Returns the extract ID and initial status."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
        async def create_data_extract(
            extract_data: dict[str, Any],
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "create_data_extract")
            if cached is not None:
                return cached
            result = await call_tool_workflow(
                client,
                _create_data_extract,
                {"extract_data": extract_data},
                params_model=CreateDataExtractParams,
            )
            await store_idempotency(request_id, "create_data_extract", result)
            return result


__all__ = ["register"]

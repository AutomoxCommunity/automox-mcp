"""Advanced device search tools (Server Groups API v2) for Automox MCP."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from ..client import AutomoxClient
from ..utils.tooling import (
    call_tool_workflow,
    maybe_format_markdown,
)
from ..workflows.device_search import (
    advanced_device_search as _advanced_device_search,
)
from ..workflows.device_search import (
    device_search_typeahead as _device_search_typeahead,
)
from ..workflows.device_search import (
    get_device_assignments as _get_device_assignments,
)
from ..workflows.device_search import (
    get_device_by_uuid as _get_device_by_uuid,
)
from ..workflows.device_search import (
    get_device_metadata_fields as _get_device_metadata_fields,
)
from ..workflows.device_search import (
    list_saved_searches as _list_saved_searches,
)

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register advanced device search tools."""

    @server.tool(
        name="list_saved_searches",
        description=(
            "List saved device searches from the Advanced Device Search API. "
            "Returns saved search names, queries, and metadata."
        ),
    )
    async def list_saved_searches(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(client, _list_saved_searches, {})
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="advanced_device_search",
        description=(
            "Execute an advanced device search using structured query language. "
            "Enables complex queries like 'find all Windows devices not seen in 30 days' "
            "using field-based filtering. Pass the query as a dict with filter conditions."
        ),
    )
    async def advanced_device_search(
        query: dict[str, Any] | None = None,
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            _advanced_device_search,
            {"query": query, "page": page, "limit": limit},
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="device_search_typeahead",
        description=(
            "Get typeahead suggestions for device search fields. "
            "Useful for discovering valid values when building advanced device queries."
        ),
    )
    async def device_search_typeahead(
        field: str,
        prefix: str,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            _device_search_typeahead,
            {"field": field, "prefix": prefix},
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_device_metadata_fields",
        description=(
            "Get available fields for device queries. "
            "Returns the field names and types supported by the advanced device search API."
        ),
    )
    async def get_device_metadata_fields(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(client, _get_device_metadata_fields, {})
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_device_assignments",
        description=("Get device-to-policy and device-to-group assignments."),
    )
    async def get_device_assignments(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(client, _get_device_assignments, {})
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_device_by_uuid",
        description=(
            "Get device details by UUID using the Server Groups API v2. "
            "Provides device information via UUID-based lookup."
        ),
    )
    async def get_device_by_uuid(
        device_uuid: str,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            _get_device_by_uuid,
            {"device_uuid": device_uuid},
        )
        return maybe_format_markdown(result, output_format)


__all__ = ["register"]

"""Worklet catalog tools for Automox MCP."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from ..client import AutomoxClient
from ..schemas import (
    GetWisItemParams,
    SearchWisParams,
)
from ..utils.tooling import (
    call_tool_workflow,
    maybe_format_markdown,
)
from ..workflows.worklets import get_worklet_detail as _get_worklet_detail
from ..workflows.worklets import search_worklet_catalog as _search_worklet_catalog

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register worklet catalog tools."""

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
        result = await call_tool_workflow(
            client,
            _search_worklet_catalog,
            params,
            params_model=SearchWisParams,
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
        result = await call_tool_workflow(
            client,
            _get_worklet_detail,
            params,
            params_model=GetWisItemParams,
        )
        return maybe_format_markdown(result, output_format)


__all__ = ["register"]

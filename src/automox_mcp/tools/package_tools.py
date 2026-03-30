"""Package-related tools for Automox MCP."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from .. import workflows
from ..client import AutomoxClient
from ..schemas import (
    GetDevicePackagesParams,
    GetOrganizationPackagesParams,
)
from ..utils.tooling import (
    call_tool_workflow,
    maybe_format_markdown,
)

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register package-related tools."""

    @server.tool(
        name="list_device_packages",
        description=(
            "List software packages installed on a specific Automox device. "
            "Returns package names, versions, patch status, and severity."
        ),
    )
    async def list_device_packages(
        device_id: int,
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "device_id": device_id,
            "page": page,
            "limit": limit,
        }
        result = await call_tool_workflow(
            client,
            workflows.list_device_packages,
            params,
            params_model=GetDevicePackagesParams,
            inject_org_id=True,
        )

        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="search_org_packages",
        description=(
            "Search software packages across the Automox organization. "
            "Filter by managed status or packages awaiting installation."
        ),
    )
    async def search_org_packages(
        include_unmanaged: bool | None = None,
        awaiting: bool | None = None,
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "include_unmanaged": include_unmanaged,
            "awaiting": awaiting,
            "page": page,
            "limit": limit,
        }
        result = await call_tool_workflow(
            client,
            workflows.search_org_packages,
            params,
            params_model=GetOrganizationPackagesParams,
        )

        return maybe_format_markdown(result, output_format)


__all__ = ["register"]

"""Package-related tools for Automox MCP."""

from __future__ import annotations

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


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register package-related tools."""

    @server.tool(
        name="list_device_packages",
        description=(
            "List software packages on a specific Automox device. Returns "
            "package name, version, `installed` (boolean install state), "
            "`repo`, `is_managed`, and `severity`. There is no patch-status "
            "field in the response; install state comes from the `installed` "
            "boolean. `severity` is one of critical/high/medium/no_known_cves "
            "or JSON null (live-verified); low/none/unknown exist per spec but "
            "were not observed live. JSON null means no severity assessment was "
            "recorded (not a safety claim); no_known_cves means scanned with no "
            "known CVEs. See metadata.field_notes.severity. By default returns "
            "the complete package set (auto-paginated), so it is reliable for "
            "'is package X installed?' checks. Pass an explicit `page` to fetch "
            "a single page instead."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
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
            "Search software packages across the Automox organization. Filter "
            "by managed status (`include_unmanaged`) or install state "
            "(`awaiting`: true = available but not installed, false = already "
            "installed -- per spec; note this is inverted from a naive reading "
            "of the word). `awaiting` is a request filter only, NOT a field in "
            "the response. Returns package name, version, `is_managed`, and "
            "`severity`. `severity` vocabulary is the same as "
            "list_device_packages: critical/high/medium/no_known_cves or JSON "
            "null observed live, with low/none/unknown present in the spec enum "
            "but unobserved. See metadata.field_notes.severity."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
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

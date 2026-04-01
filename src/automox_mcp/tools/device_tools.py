"""Device-related tools for Automox MCP."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastmcp import FastMCP

from .. import workflows
from ..client import AutomoxClient
from ..schemas import (
    DeviceDetailParams,
    DeviceHealthSummaryParams,
    DeviceIdOnlyParams,
    DeviceInventoryOverviewParams,
    DeviceInventoryParams,
    DeviceSearchParams,
    DevicesNeedingAttentionParams,
    IssueDeviceCommandParams,
)
from ..utils.tooling import (
    call_tool_workflow,
    check_idempotency,
    maybe_format_markdown,
    store_idempotency,
)

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register device-related tools."""

    @server.tool(
        name="list_devices",
        description=(
            "List devices with detailed per-device information including hostname, OS, "
            "policy status, and patch status. Use this to explore and investigate "
            "specific devices, optionally filtered by management/policy status. For "
            "aggregate statistics and health metrics, use device_health_metrics instead."
        ),
    )
    async def list_devices(
        group_id: int | None = None,
        limit: int | None = 500,
        include_unmanaged: bool | None = True,
        policy_status: str | None = None,
        managed: bool | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "group_id": group_id,
            "limit": limit,
            "include_unmanaged": include_unmanaged,
            "policy_status": policy_status,
            "managed": managed,
        }
        result = await call_tool_workflow(
            client,
            workflows.list_device_inventory,
            params,
            params_model=DeviceInventoryOverviewParams,
        )

        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="device_detail",
        description="Return detailed information and recent activity for a device.",
    )
    async def device_detail(
        device_id: int,
        include_packages: bool | None = False,
        include_inventory: bool | None = True,
        include_queue: bool | None = True,
        include_raw_details: bool | None = False,
    ) -> dict[str, Any]:
        params = {
            "device_id": device_id,
            "include_packages": include_packages,
            "include_inventory": include_inventory,
            "include_queue": include_queue,
            "include_raw_details": include_raw_details,
        }
        return await call_tool_workflow(
            client, workflows.describe_device, params, params_model=DeviceDetailParams
        )

    @server.tool(
        name="devices_needing_attention",
        description="Surface Automox devices flagged for immediate action.",
    )
    async def devices_needing_attention(
        group_id: int | None = None,
        limit: int | None = 20,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "group_id": group_id,
            "limit": limit,
        }
        result = await call_tool_workflow(
            client,
            workflows.list_devices_needing_attention,
            params,
            params_model=DevicesNeedingAttentionParams,
        )

        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="search_devices",
        description=(
            "Search Automox devices by hostname (including custom name), IP, tag, severity of "
            "missing patches, or patch status (only 'missing' is supported)."
        ),
    )
    async def search_devices_tool(
        hostname_contains: str | None = None,
        ip_address: str | None = None,
        tag: str | None = None,
        patch_status: Literal["missing"] | None = None,
        severity: list[str] | str | None = None,
        managed: bool | None = None,
        group_id: int | None = None,
        limit: int | None = 50,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "hostname_contains": hostname_contains,
            "ip_address": ip_address,
            "tag": tag,
            "patch_status": patch_status,
            "severity": severity,
            "managed": managed,
            "group_id": group_id,
            "limit": limit,
        }
        result = await call_tool_workflow(
            client,
            workflows.search_devices,
            params,
            params_model=DeviceSearchParams,
        )

        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="device_health_metrics",
        description=(
            "Aggregate organization-wide device health statistics including managed/unmanaged "
            "breakdown, device status breakdown, compliance metrics, and check-in recency "
            "analysis. Use this for monitoring dashboards and getting a fleet-wide health overview."
        ),
    )
    async def device_health_metrics(
        group_id: int | None = None,
        include_unmanaged: bool | None = False,
        limit: int | None = 500,
        max_stale_devices: int | None = 25,
    ) -> dict[str, Any]:
        params = {
            "group_id": group_id,
            "include_unmanaged": include_unmanaged,
            "limit": limit,
            "max_stale_devices": max_stale_devices,
        }
        return await call_tool_workflow(
            client,
            workflows.summarize_device_health,
            params,
            params_model=DeviceHealthSummaryParams,
        )

    @server.tool(
        name="get_device_inventory",
        description=(
            "Retrieve detailed device inventory data including hardware, network, "
            "security, services, system, and user information. Optionally filter "
            "by category. Uses the Console API device-details endpoint."
        ),
    )
    async def get_device_inventory_tool(
        device_id: int,
        category: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"device_id": device_id}
        if category is not None:
            params["category"] = category
        return await call_tool_workflow(
            client,
            workflows.get_device_inventory,
            params,
            params_model=DeviceInventoryParams,
        )

    @server.tool(
        name="get_device_inventory_categories",
        description=(
            "List available inventory categories for a device. Categories are "
            "dynamic per device. Use this to discover what inventory data is "
            "available before requesting specific categories."
        ),
    )
    async def get_device_inventory_categories_tool(
        device_id: int,
    ) -> dict[str, Any]:
        params = {"device_id": device_id}
        return await call_tool_workflow(
            client,
            workflows.get_device_inventory_categories,
            params,
            params_model=DeviceIdOnlyParams,
        )

    if not read_only:

        @server.tool(
            name="execute_device_command",
            description="Issue an immediate command to a device (scan, patch, or reboot).",
            annotations={"destructiveHint": True},
        )
        async def execute_device_command(
            device_id: int,
            command_type: str,
            patch_names: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "execute_device_command")
            if cached is not None:
                return cached

            params = {
                "device_id": device_id,
                "command_type": command_type,
                "patch_names": patch_names,
            }
            result = await call_tool_workflow(
                client,
                workflows.issue_device_command,
                params,
                params_model=IssueDeviceCommandParams,
            )
            await store_idempotency(request_id, "execute_device_command", result)
            return result


__all__ = ["register"]

"""Device-related tools for Automox MCP."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastmcp import FastMCP

from .. import workflows
from ..client import AutomoxClient
from ..schemas import (
    BatchUpdateDevicesParams,
    DeviceDetailParams,
    DeviceHealthSummaryParams,
    DeviceIdOnlyParams,
    DeviceInventoryOverviewParams,
    DeviceInventoryParams,
    DeviceSearchParams,
    DevicesNeedingAttentionParams,
    IssueDeviceCommandParams,
    UpdateDeviceParams,
)
from ..utils.tooling import (
    call_tool_workflow,
    check_idempotency,
    is_device_deletion_allowed,
    maybe_format_markdown,
    release_idempotency,
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
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
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
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
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
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
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
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
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
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
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
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
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
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
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
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
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
            try:
                result = await call_tool_workflow(
                    client,
                    workflows.issue_device_command,
                    params,
                    params_model=IssueDeviceCommandParams,
                )
            except BaseException:
                await release_idempotency(request_id, "execute_device_command")
                raise
            await store_idempotency(request_id, "execute_device_command", result)
            return result

        @server.tool(
            name="batch_update_devices",
            description=(
                "Apply bulk attribute actions to many devices at once (up to 500). "
                "Currently supports tag apply/remove via actions like "
                "{'attribute': 'tags', 'action': 'apply', 'value': ['env:prod']}."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
        async def batch_update_devices(
            devices: list[int],
            actions: list[dict[str, Any]],
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "batch_update_devices")
            if cached is not None:
                return cached

            try:
                result = await call_tool_workflow(
                    client,
                    workflows.batch_update_devices,
                    {"devices": devices, "actions": actions},
                    params_model=BatchUpdateDevicesParams,
                )
            except BaseException:
                await release_idempotency(request_id, "batch_update_devices")
                raise
            await store_idempotency(request_id, "batch_update_devices", result)
            return result

        @server.tool(
            name="update_device",
            description=(
                "Update a single device's mutable attributes: custom_name, "
                "server_group_id, exception (policy-enforcement exclusion), tags, and "
                "ip_addrs. Fills the single-device gap that batch_update_devices "
                "(tags-only, bulk) does not cover — e.g. renaming a device or moving it "
                "to a server group. Supply only the fields you want to change; at least "
                "one is required."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def update_device(
            device_id: int,
            custom_name: str | None = None,
            server_group_id: int | None = None,
            exception: bool | None = None,
            tags: list[str] | None = None,
            ip_addrs: list[str] | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "update_device")
            if cached is not None:
                return cached

            params = {
                "device_id": device_id,
                "custom_name": custom_name,
                "server_group_id": server_group_id,
                "exception": exception,
                "tags": tags,
                "ip_addrs": ip_addrs,
            }
            try:
                result = await call_tool_workflow(
                    client,
                    workflows.update_device,
                    params,
                    params_model=UpdateDeviceParams,
                )
            except BaseException:
                await release_idempotency(request_id, "update_device")
                raise
            await store_idempotency(request_id, "update_device", result)
            return result

        # Device deletion is opt-in beyond write mode: DELETE /servers/{id}
        # destroys the device record and its history with no create-device
        # counterpart (agents self-register), so a wrongly deleted record is not
        # reconstructable through the MCP and per-call confirmation cannot
        # restore it. Gated by AUTOMOX_MCP_ALLOW_DELETE_DEVICE (category B).
        if is_device_deletion_allowed():

            @server.tool(
                name="delete_device",
                description=(
                    "Permanently delete a device (server) record and its history "
                    "via DELETE /servers/{id}. Irreversible and not reconstructable "
                    "through the MCP — there is no create-device counterpart "
                    "(agents self-register). Requires "
                    "AUTOMOX_MCP_ALLOW_DELETE_DEVICE=true."
                ),
                annotations={
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": False,
                    "openWorldHint": True,
                },
            )
            async def delete_device(
                device_id: int,
                request_id: str | None = None,
            ) -> dict[str, Any]:
                cached = await check_idempotency(request_id, "delete_device")
                if cached is not None:
                    return cached

                try:
                    result = await call_tool_workflow(
                        client,
                        workflows.delete_device,
                        {"device_id": device_id},
                        params_model=DeviceIdOnlyParams,
                    )
                except BaseException:
                    await release_idempotency(request_id, "delete_device")
                    raise
                await store_idempotency(request_id, "delete_device", result)
                return result


__all__ = ["register"]

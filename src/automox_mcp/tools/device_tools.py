"""Device-related tools for Automox MCP."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from .. import workflows
from ..client import AutomoxAPIError, AutomoxClient
from ..schemas import (
    DeviceDetailParams,
    DeviceHealthSummaryParams,
    DeviceInventoryOverviewParams,
    DeviceSearchParams,
    DevicesNeedingAttentionParams,
    IssueDeviceCommandParams,
    OrgIdContextMixin,
    OrgIdRequiredMixin,
)
from ..utils.tooling import (
    RateLimitError,
    as_tool_response,
    enforce_rate_limit,
    format_error,
)


def register(server: FastMCP) -> None:
    """Register device-related tools."""

    async def _call(
        func: Callable[..., Awaitable[dict[str, Any]]],
        params_model: type[BaseModel],
        raw_params: dict[str, Any],
        api: str | None = None,
    ) -> dict[str, Any]:
        try:
            await enforce_rate_limit(api)
            client = AutomoxClient(default_api=api)
            client_org_id = getattr(client, "org_id", None)
            async with client as session:
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
                result: dict[str, Any] = await func(session, **payload)
        except (ValidationError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        except RateLimitError as exc:
            raise ToolError(str(exc)) from exc
        except AutomoxAPIError as exc:
            raise ToolError(format_error(exc)) from exc
        return as_tool_response(result)

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
    ) -> dict[str, Any]:
        params = {
            "group_id": group_id,
            "limit": limit,
            "include_unmanaged": include_unmanaged,
            "policy_status": policy_status,
            "managed": managed,
        }
        return await _call(
            workflows.list_device_inventory,
            DeviceInventoryOverviewParams,
            params,
            api="console",
        )

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
        return await _call(workflows.describe_device, DeviceDetailParams, params, api="console")

    @server.tool(
        name="devices_needing_attention",
        description="Surface Automox devices flagged for immediate action.",
    )
    async def devices_needing_attention(
        group_id: int | None = None,
        limit: int | None = 20,
    ) -> dict[str, Any]:
        params = {
            "group_id": group_id,
            "limit": limit,
        }
        return await _call(
            workflows.list_devices_needing_attention,
            DevicesNeedingAttentionParams,
            params,
            api="console",
        )

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
        return await _call(
            workflows.search_devices,
            DeviceSearchParams,
            params,
            api="console",
        )

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
        return await _call(
            workflows.summarize_device_health,
            DeviceHealthSummaryParams,
            params,
            api="console",
        )

    @server.tool(
        name="execute_device_command",
        description="Issue an immediate command to a device (scan, patch, or reboot).",
        annotations={"destructiveHint": True},
    )
    async def execute_device_command(
        device_id: int,
        command_type: str,
        patch_names: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "device_id": device_id,
            "command_type": command_type,
            "patch_names": patch_names,
        }
        return await _call(
            workflows.issue_device_command,
            IssueDeviceCommandParams,
            params,
            api="console",
        )


__all__ = ["register"]

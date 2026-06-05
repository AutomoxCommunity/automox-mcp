"""Compound tools that combine multiple API calls into single high-value responses."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .. import workflows
from ..client import AutomoxClient
from ..schemas import (
    ComplianceSnapshotParams,
    DeviceFullProfileParams,
    PatchTuesdayReadinessParams,
)
from ..utils.tooling import call_tool_workflow


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register compound tools."""

    @server.tool(
        name="get_patch_tuesday_readiness",
        description=(
            "Combined view of pre-patch report, pending approvals, and patch policy "
            "schedules. Answers 'Are we ready for Patch Tuesday?' in a single call. "
            "Policy `schedule_days` bitmasks carry a `schedule_days_decoded` "
            "sibling; `schedule_time` is a bare HH:MM string with no timezone "
            "marker. Patch `severity` values use the vocabulary "
            "critical/high/medium/low/no_known_cves (null when unrated)."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_patch_tuesday_readiness(
        group_id: int | None = None,
        detail_limit: int = 10,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"detail_limit": detail_limit}
        if group_id is not None:
            params["group_id"] = group_id
        return await call_tool_workflow(
            client,
            workflows.compound.get_patch_tuesday_readiness,
            params,
            params_model=PatchTuesdayReadinessParams,
            org_uuid_field="org_uuid",
            allow_account_uuid=True,
        )

    @server.tool(
        name="get_compliance_snapshot",
        description=(
            "Combined view of non-compliant devices, fleet health metrics, and "
            "policy statistics. Answers 'What is our compliance posture?' in a single call."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_compliance_snapshot(
        group_id: int | None = None,
        detail_limit: int = 10,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"detail_limit": detail_limit}
        if group_id is not None:
            params["group_id"] = group_id
        return await call_tool_workflow(
            client,
            workflows.compound.get_compliance_snapshot,
            params,
            params_model=ComplianceSnapshotParams,
        )

    @server.tool(
        name="get_device_full_profile",
        description=(
            "Complete device profile combining device detail, inventory summary, "
            "packages, and policy assignments in a single call. Inventory is "
            "summarized with key values per category. Packages capped at "
            "max_packages (default 25). pending_commands entries carry "
            "command_type and scheduled_time (the queued exec_time). Use "
            "get_device_inventory or list_device_packages for full data."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_device_full_profile(
        device_id: int,
        max_packages: int = 25,
        detail_limit: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "device_id": device_id,
            "max_packages": max_packages,
        }
        if detail_limit is not None:
            params["detail_limit"] = detail_limit
        return await call_tool_workflow(
            client,
            workflows.compound.get_device_full_profile,
            params,
            params_model=DeviceFullProfileParams,
        )


__all__ = ["register"]

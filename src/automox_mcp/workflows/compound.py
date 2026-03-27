"""Compound workflows that combine multiple API calls into single high-value responses."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient
from . import devices, packages, policy, reports


def _settle(
    results: tuple[Any, ...],
    labels: tuple[str, ...],
) -> tuple[list[Any], list[str]]:
    """Separate gather(return_exceptions=True) results into values and errors."""
    values: list[Any] = []
    errors: list[str] = []
    for result, label in zip(results, labels, strict=True):
        if isinstance(result, BaseException):
            errors.append(f"{label}: {result}")
            values.append({})
        else:
            values.append(result)
    return values, errors


async def get_patch_tuesday_readiness(
    client: AutomoxClient,
    *,
    org_id: int,
    org_uuid: str,
    group_id: int | None = None,
) -> dict[str, Any]:
    """Combine pre-patch report, pending approvals, and policy schedules into one view.

    Answers: "Are we ready for Patch Tuesday?"
    """
    raw_results = await asyncio.gather(
        reports.get_prepatch_report(client, org_id=org_id, group_id=group_id),
        policy.summarize_patch_approvals(client, org_id=org_id),
        policy.summarize_policies(
            client,
            org_id=org_id,
            limit=200,
            page=0,
            include_inactive=False,
        ),
        return_exceptions=True,
    )

    (prepatch, approvals, catalog), errors = _settle(
        raw_results,
        ("prepatch_report", "patch_approvals", "policy_catalog"),
    )

    patch_policies: list[dict[str, Any]] = []
    catalog_data = catalog.get("data") or {}
    all_policies = catalog_data.get("policies") or []
    for p in all_policies:
        if isinstance(p, Mapping) and str(p.get("type") or "").lower() == "patch":
            patch_policies.append(dict(p))

    prepatch_data = prepatch.get("data") or {}
    approvals_data = approvals.get("data") or {}

    pending_approval_count = 0
    approval_items = approvals_data.get("approvals") or []
    if isinstance(approval_items, list):
        pending_approval_count = sum(
            1
            for a in approval_items
            if isinstance(a, Mapping) and a.get("status") in ("pending", "Pending")
        )

    return {
        "data": {
            "prepatch_report": {
                "total_devices_needing_patches": prepatch_data.get("total_devices", 0),
                "summary": prepatch_data.get("summary", {}),
                "devices": prepatch_data.get("devices", []),
            },
            "patch_approvals": {
                "pending_count": pending_approval_count,
                "approvals": approval_items,
            },
            "patch_policy_schedules": [
                {
                    "id": p.get("policy_id"),
                    "name": p.get("name"),
                    "status": p.get("status"),
                    "schedule_days": p.get("schedule_days"),
                    "schedule_time": p.get("schedule_time"),
                    "next_run": p.get("next_run"),
                    "server_groups": p.get("server_groups"),
                }
                for p in patch_policies
            ],
            "readiness_summary": {
                "devices_needing_patches": prepatch_data.get("total_devices", 0),
                "pending_approvals": pending_approval_count,
                "active_patch_policies": sum(
                    1
                    for p in patch_policies
                    if str(p.get("status") or "").lower() not in ("inactive", "disabled")
                ),
            },
        },
        "metadata": {
            "errors": errors if errors else None,
        },
    }


async def get_compliance_snapshot(
    client: AutomoxClient,
    *,
    org_id: int,
    group_id: int | None = None,
) -> dict[str, Any]:
    """Combine non-compliant report, health metrics, and policy stats into one view.

    Answers: "What's our overall compliance posture?"
    """
    raw_results = await asyncio.gather(
        reports.get_noncompliant_report(client, org_id=org_id, group_id=group_id),
        devices.summarize_device_health(
            client,
            org_id=org_id,
            group_id=group_id,
            include_unmanaged=False,
            limit=500,
            max_stale_devices=10,
        ),
        policy.summarize_policies(
            client,
            org_id=org_id,
            limit=200,
            page=0,
            include_inactive=False,
        ),
        return_exceptions=True,
    )

    (noncompliant, health, catalog), errors = _settle(
        raw_results,
        ("noncompliant_report", "device_health", "policy_catalog"),
    )

    policy_summary: dict[str, Any] = {}
    catalog_data = catalog.get("data") or {}
    all_policies = catalog_data.get("policies") or []
    type_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for p in all_policies:
        if isinstance(p, Mapping):
            ptype = str(p.get("type", "unknown"))
            type_counts[ptype] = type_counts.get(ptype, 0) + 1
            pstatus = str(p.get("status", "unknown"))
            status_counts[pstatus] = status_counts.get(pstatus, 0) + 1
    policy_summary = {
        "total_policies": catalog_data.get("total_policies_considered")
        or catalog_data.get("total_policies_available")
        or len(all_policies),
        "by_type": type_counts,
        "by_status": status_counts,
    }

    noncompliant_data = noncompliant.get("data") or {}
    health_data = health.get("data") or {}

    total_devices = health_data.get("total_devices", 0)
    noncompliant_count = noncompliant_data.get("total_devices", 0)
    compliant_count = max(0, total_devices - noncompliant_count)
    compliance_rate = round(compliant_count / total_devices * 100, 1) if total_devices > 0 else 0

    return {
        "data": {
            "compliance_overview": {
                "total_devices": total_devices,
                "compliant_devices": compliant_count,
                "noncompliant_devices": noncompliant_count,
                "compliance_rate_percent": compliance_rate,
            },
            "noncompliant_report": {
                "summary": noncompliant_data.get("summary", {}),
                "devices": noncompliant_data.get("devices", []),
            },
            "device_health": {
                "status_breakdown": health_data.get("device_status_breakdown", {}),
                "check_in_recency": health_data.get("check_in_recency_breakdown", {}),
                "stale_devices": health_data.get("stale_devices", []),
            },
            "policy_summary": policy_summary,
        },
        "metadata": {
            "errors": errors if errors else None,
        },
    }


async def get_device_full_profile(
    client: AutomoxClient,
    *,
    org_id: int,
    device_id: int,
    max_packages: int = 25,
) -> dict[str, Any]:
    """Combine device detail, packages, inventory, and policy status into one view.

    Answers: "Give me the full profile for [device]."

    Inventory is summarized (counts + key values per category) to keep
    the response readable.  Packages are capped at *max_packages* with a
    note indicating how many were omitted.  Use get_device_inventory or
    list_device_packages for full data.
    """
    labels = ("device_detail", "device_inventory", "device_packages")

    raw_results = await asyncio.gather(
        devices.describe_device(
            client,
            org_id=org_id,
            device_id=device_id,
            include_packages=False,
            include_inventory=False,
            include_queue=True,
        ),
        devices.get_device_inventory(
            client,
            org_id=org_id,
            device_id=device_id,
        ),
        packages.list_device_packages(
            client,
            org_id=org_id,
            device_id=device_id,
            limit=max_packages,
        ),
        return_exceptions=True,
    )

    (device_info, inventory, full_packages), errors = _settle(raw_results, labels)

    section_status: dict[str, str] = {
        label: "failed" if isinstance(result, BaseException) else "complete"
        for result, label in zip(raw_results, labels, strict=True)
    }

    device_data = device_info.get("data") or {}
    inventory_data = inventory.get("data") or {}
    packages_data = full_packages.get("data") or {}

    # Summarize inventory: counts + key values per category (not full data)
    raw_categories = inventory_data.get("categories") or {}
    inventory_summary: dict[str, Any] = {}
    for cat_name, cat_content in raw_categories.items():
        sub_cats = cat_content.get("sub_categories", {})
        sub_summaries: dict[str, Any] = {}
        for sub_name, sub_content in sub_cats.items():
            items = sub_content.get("items", [])
            # Extract key-value pairs for simple scalar items
            key_values: dict[str, Any] = {}
            for item in items:
                val = item.get("value")
                friendly = item.get("friendly_name") or item.get("name")
                # Only include scalar values (skip large nested structures)
                if friendly and isinstance(val, (str, int, float, bool)) and val != "":
                    key_values[friendly] = val
            sub_summaries[sub_name] = {
                "item_count": sub_content.get("item_count", 0),
                "key_values": key_values if key_values else None,
            }
        inventory_summary[cat_name] = {
            "sub_category_count": len(sub_cats),
            "item_count": sum(s.get("item_count", 0) for s in sub_cats.values()),
            "sub_categories": sub_summaries,
        }

    total_inventory_items = inventory_data.get("total_items", 0)

    # Cap packages
    all_packages = packages_data.get("packages", [])
    total_packages = packages_data.get("total_packages", 0)
    packages_preview = all_packages[:max_packages]
    packages_truncated = total_packages > len(packages_preview)

    # Policy assignments
    policy_assignments = device_data.get("policy_assignments", {})
    total_policies = policy_assignments.get("total", 0)

    return {
        "data": {
            "device": device_data.get("core", {}),
            "policy_assignments": policy_assignments,
            "pending_commands": device_data.get("pending_commands", []),
            "device_facts": device_data.get("device_facts"),
            "inventory": {
                "total_categories": len(inventory_summary),
                "total_items": total_inventory_items,
                "categories": inventory_summary,
                "note": "Summarized view — use get_device_inventory for full data",
            },
            "packages": {
                "total": total_packages,
                "returned": len(packages_preview),
                "truncated": packages_truncated,
                "packages": packages_preview,
                "note": (
                    f"Showing {len(packages_preview)} of {total_packages} packages — "
                    "use list_device_packages for full list"
                )
                if packages_truncated
                else None,
            },
        },
        "metadata": {
            "errors": errors if errors else None,
            "section_status": section_status,
            "data_complete": not errors,
            "counts": {
                "inventory_categories": len(inventory_summary),
                "inventory_items": total_inventory_items,
                "packages_total": total_packages,
                "packages_returned": len(packages_preview),
                "policy_assignments": total_policies,
                "pending_commands": len(device_data.get("pending_commands", [])),
            },
        },
    }

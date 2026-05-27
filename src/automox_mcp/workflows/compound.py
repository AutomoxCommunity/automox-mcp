"""Compound workflows that combine multiple API calls into single high-value responses."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient
from ..utils.response import build_section_summary, build_section_summary_notes
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
    detail_limit: int = 10,
) -> dict[str, Any]:
    """Combine pre-patch report, pending approvals, and policy schedules into one view.

    Answers: "Are we ready for Patch Tuesday?"

    Each inner list is capped at ``detail_limit`` (default 10) so the response
    fits the token budget on tenants of any size. Counts and aggregates are
    always returned in full; sections that exceed the cap surface a
    ``metadata.section_summaries.<key>`` entry with ``total``, ``returned``,
    ``has_more``, and a ``follow_up_tool``/``follow_up_args_hint`` pointing
    at the underlying detail tool (#53 compound contract).
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

    prepatch_devices_full = prepatch_data.get("devices") or []
    approval_items_full = approval_items if isinstance(approval_items, list) else []
    patch_policy_entries_full = [
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
    ]

    prepatch_devices_preview = prepatch_devices_full[:detail_limit]
    approvals_preview = approval_items_full[:detail_limit]
    patch_policy_schedules_preview = patch_policy_entries_full[:detail_limit]

    follow_up_hint = {"group_id": group_id} if group_id is not None else {}
    section_summaries: dict[str, Any] = {}
    for key, full, preview, tool, args in (
        (
            "prepatch_report.devices",
            prepatch_devices_full,
            prepatch_devices_preview,
            "get_prepatch_report",
            follow_up_hint,
        ),
        (
            "patch_approvals.approvals",
            approval_items_full,
            approvals_preview,
            "patch_approvals_summary",
            {},
        ),
        (
            "patch_policy_schedules",
            patch_policy_entries_full,
            patch_policy_schedules_preview,
            "policy_catalog",
            # The detail tool returns all policies; the caller filters by
            # type=patch client-side (no native type filter today).
            {"include_inactive": False, "limit": 200},
        ),
    ):
        summary = build_section_summary(
            total=len(full),
            returned=len(preview),
            follow_up_tool=tool,
            follow_up_args_hint=args,
        )
        if summary is not None:
            section_summaries[key] = summary

    metadata: dict[str, Any] = {
        "errors": errors if errors else None,
        "detail_limit": detail_limit,
    }
    if section_summaries:
        metadata["section_summaries"] = section_summaries
        metadata["notes"] = build_section_summary_notes(
            section_summaries, detail_limit=detail_limit
        )

    return {
        "data": {
            "prepatch_report": {
                "total_devices_needing_patches": prepatch_data.get("total_devices", 0),
                "summary": prepatch_data.get("summary", {}),
                "devices": prepatch_devices_preview,
            },
            "patch_approvals": {
                "pending_count": pending_approval_count,
                "approvals": approvals_preview,
            },
            "patch_policy_schedules": patch_policy_schedules_preview,
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
        "metadata": metadata,
    }


async def get_compliance_snapshot(
    client: AutomoxClient,
    *,
    org_id: int,
    group_id: int | None = None,
    detail_limit: int = 10,
) -> dict[str, Any]:
    """Combine non-compliant report, health metrics, and policy stats into one view.

    Answers: "What's our overall compliance posture?"

    Each inner list is capped at ``detail_limit`` (default 10); see
    :func:`get_patch_tuesday_readiness` for the compound-tool contract
    (#53). Counts and aggregates are always returned in full.
    """
    raw_results = await asyncio.gather(
        reports.get_noncompliant_report(client, org_id=org_id, group_id=group_id),
        devices.summarize_device_health(
            client,
            org_id=org_id,
            group_id=group_id,
            include_unmanaged=False,
            limit=500,
            max_stale_devices=max(detail_limit, 10),
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

    noncompliant_devices_full = noncompliant_data.get("devices") or []
    noncompliant_devices_preview = noncompliant_devices_full[:detail_limit]

    # summarize_device_health already capped stale_devices at max_stale_devices,
    # but its metadata.stale_device_count reports the true fleet-wide count
    # so we can still emit an honest section_summary.
    stale_devices_preview = (health_data.get("stale_devices") or [])[:detail_limit]
    health_meta = health.get("metadata") if isinstance(health, Mapping) else None
    stale_total = (
        health_meta.get("stale_device_count") if isinstance(health_meta, Mapping) else None
    )
    if not isinstance(stale_total, int):
        stale_total = len(stale_devices_preview)

    follow_up_hint = {"group_id": group_id} if group_id is not None else {}
    section_summaries: dict[str, Any] = {}
    for key, full, preview, tool, args in (
        (
            "noncompliant_report.devices",
            noncompliant_devices_full,
            noncompliant_devices_preview,
            "get_noncompliant_report",
            follow_up_hint,
        ),
    ):
        summary = build_section_summary(
            total=len(full),
            returned=len(preview),
            follow_up_tool=tool,
            follow_up_args_hint=args,
        )
        if summary is not None:
            section_summaries[key] = summary

    # stale_devices uses the upstream-reported total instead of the local
    # length, since summarize_device_health caps its own output.
    stale_summary = build_section_summary(
        total=stale_total,
        returned=len(stale_devices_preview),
        follow_up_tool="device_health_metrics",
        follow_up_args_hint=follow_up_hint,
    )
    if stale_summary is not None:
        section_summaries["device_health.stale_devices"] = stale_summary

    metadata: dict[str, Any] = {
        "errors": errors if errors else None,
        "detail_limit": detail_limit,
    }
    if section_summaries:
        metadata["section_summaries"] = section_summaries
        metadata["notes"] = build_section_summary_notes(
            section_summaries, detail_limit=detail_limit
        )

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
                "devices": noncompliant_devices_preview,
            },
            "device_health": {
                "status_breakdown": health_data.get("device_status_breakdown", {}),
                "check_in_recency": health_data.get("check_in_recency_breakdown", {}),
                "stale_devices": stale_devices_preview,
            },
            "policy_summary": policy_summary,
        },
        "metadata": metadata,
    }


async def get_device_full_profile(
    client: AutomoxClient,
    *,
    org_id: int,
    device_id: int,
    max_packages: int = 25,
    detail_limit: int | None = None,
) -> dict[str, Any]:
    """Combine device detail, packages, inventory, and policy status into one view.

    Answers: "Give me the full profile for [device]."

    Inventory is summarized server-side (counts + key values per category)
    because the raw payload is dict-structured rather than a flat list.
    The ``packages.packages`` array is capped at ``detail_limit`` and the
    canonical ``metadata.section_summaries`` block points at
    ``list_device_packages`` for the full list. ``max_packages`` is a
    legacy alias retained for backwards-compat — when ``detail_limit`` is
    omitted, ``max_packages`` is used.
    """
    labels = ("device_detail", "device_inventory", "device_packages")

    effective_limit = detail_limit if detail_limit is not None else max_packages

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
            limit=effective_limit,
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
    packages_preview = all_packages[:effective_limit]
    packages_truncated = total_packages > len(packages_preview)

    # Policy assignments
    policy_assignments = device_data.get("policy_assignments", {})
    total_policies = policy_assignments.get("total", 0)

    section_summaries: dict[str, Any] = {}
    package_section_summary = build_section_summary(
        total=total_packages,
        returned=len(packages_preview),
        follow_up_tool="list_device_packages",
        follow_up_args_hint={"device_id": device_id},
    )
    if package_section_summary is not None:
        section_summaries["packages.packages"] = package_section_summary

    metadata: dict[str, Any] = {
        "errors": errors if errors else None,
        "section_status": section_status,
        "data_complete": not errors,
        "detail_limit": effective_limit,
        "counts": {
            "inventory_categories": len(inventory_summary),
            "inventory_items": total_inventory_items,
            "packages_total": total_packages,
            "packages_returned": len(packages_preview),
            "policy_assignments": total_policies,
            "pending_commands": len(device_data.get("pending_commands", [])),
        },
    }
    if section_summaries:
        metadata["section_summaries"] = section_summaries
        metadata["notes"] = build_section_summary_notes(
            section_summaries, detail_limit=effective_limit
        )

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
                # Legacy shape retained for backwards-compat (#53). Canonical
                # truncation state now lives in metadata.section_summaries.
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
        "metadata": metadata,
    }

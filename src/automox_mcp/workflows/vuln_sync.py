"""Vulnerability Sync / Remediations workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient
from ..utils.response import extract_list as _extract_list


def _summarize_action_set(item: Mapping[str, Any]) -> dict[str, Any]:
    """Extract key fields from an action set record.

    The Automox `/orgs/{org}/remediations/action-sets` API returns
    `id`, `configuration_id`, `organization_id`, `status`, `source`
    (object with `name`/`type`), `statistics` (nested counts under
    `issues`/`devices`/`solutions`), `created_at`, `updated_at`,
    `error`, plus user attribution fields. Earlier revisions looked
    for top-level `name`, `issue_count`, `action_count`,
    `solution_count` — none of which the API emits — so both list and
    detail endpoints returned only the 5 keys the API does have at top
    level (id/status/source/created_at/updated_at), creating bug #4a
    "no detail enrichment".
    """
    entry: dict[str, Any] = {}
    for key in (
        "id",
        "configuration_id",
        "organization_id",
        "status",
        "source",
        "created_at",
        "updated_at",
        "error",
    ):
        val = item.get(key)
        if val is not None:
            entry[key] = val

    # Pull a flat `name` out of the `source` object when possible so
    # callers don't need to navigate the nested shape.
    source = item.get("source")
    if isinstance(source, Mapping):
        source_name = source.get("name")
        if source_name and "name" not in entry:
            entry["name"] = source_name

    # Flatten the per-bucket counts in `statistics` into top-level
    # totals so the summary surfaces them at a glance.
    stats = item.get("statistics")
    if isinstance(stats, Mapping):
        issues = stats.get("issues")
        if isinstance(issues, Mapping):
            issue_count = 0
            for bucket in issues.values():
                if isinstance(bucket, Mapping):
                    bucket_count = bucket.get("count")
                    if isinstance(bucket_count, int):
                        issue_count += bucket_count
            entry["issue_count"] = issue_count

        solutions = stats.get("solutions")
        if isinstance(solutions, Mapping):
            solution_count = 0
            action_count = 0
            for bucket in solutions.values():
                if isinstance(bucket, Mapping):
                    bucket_count = bucket.get("count")
                    if isinstance(bucket_count, int):
                        solution_count += bucket_count
            entry["solution_count"] = solution_count
            entry["action_count"] = action_count

        devices = stats.get("devices")
        if isinstance(devices, Mapping):
            matched = devices.get("matched_count")
            if isinstance(matched, int):
                entry["matched_device_count"] = matched

        # Also expose the full statistics block for callers that want
        # the raw nested shape (per-issue-type, per-solution-type counts).
        entry["statistics"] = dict(stats)

    return entry


async def list_remediation_action_sets(
    client: AutomoxClient,
    *,
    org_id: int,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List vulnerability remediation action sets."""
    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    response = await client.get(
        f"/orgs/{org_id}/remediations/action-sets",
        params=params or None,
    )

    items = _extract_list(response)
    summaries = [_summarize_action_set(item) for item in items]

    return {
        "data": {
            "total_action_sets": len(summaries),
            "action_sets": summaries,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def get_action_set_detail(
    client: AutomoxClient,
    *,
    org_id: int,
    action_set_id: int,
) -> dict[str, Any]:
    """Get details for a specific action set."""
    response = await client.get(
        f"/orgs/{org_id}/remediations/action-sets/{action_set_id}",
    )

    if isinstance(response, Mapping):
        detail = _summarize_action_set(response)
    else:
        detail = {}

    return {
        "data": detail,
        "metadata": {"deprecated_endpoint": False},
    }


async def get_action_set_issues(
    client: AutomoxClient,
    *,
    org_id: int,
    action_set_id: int,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Get vulnerability issues for an action set."""
    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    response = await client.get(
        f"/orgs/{org_id}/remediations/action-sets/{action_set_id}/issues",
        params=params or None,
    )

    issues = _extract_list(response)

    return {
        "data": {
            "action_set_id": action_set_id,
            "total_issues": len(issues),
            "issues": issues,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def get_action_set_solutions(
    client: AutomoxClient,
    *,
    org_id: int,
    action_set_id: int,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Get solutions for an action set."""
    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    response = await client.get(
        f"/orgs/{org_id}/remediations/action-sets/{action_set_id}/solutions",
        params=params or None,
    )

    solutions = _extract_list(response)

    return {
        "data": {
            "action_set_id": action_set_id,
            "total_solutions": len(solutions),
            "solutions": solutions,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def get_upload_formats(
    client: AutomoxClient,
    *,
    org_id: int,
) -> dict[str, Any]:
    """Get supported CSV upload formats for action sets."""
    response = await client.get(
        f"/orgs/{org_id}/remediations/action-sets/upload/formats",
    )

    formats = _extract_list(response)

    return {
        "data": {
            "total_formats": len(formats),
            "formats": formats,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def upload_action_set(
    client: AutomoxClient,
    *,
    org_id: int,
    action_set_data: dict[str, Any],
) -> dict[str, Any]:
    """Upload a CSV-based remediation action set."""
    response = await client.post(
        f"/orgs/{org_id}/remediations/action-sets/upload",
        json_data=action_set_data,
    )

    if isinstance(response, Mapping):
        result = dict(response)
    else:
        result = {}

    return {
        "data": {
            "id": result.get("id"),
            "status": result.get("status", "pending"),
            "message": "Action set upload submitted.",
        },
        "metadata": {"deprecated_endpoint": False},
    }

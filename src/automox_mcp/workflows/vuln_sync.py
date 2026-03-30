"""Vulnerability Sync / Remediations workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient
from ..utils.response import extract_list as _extract_list


def _summarize_action_set(item: Mapping[str, Any]) -> dict[str, Any]:
    """Extract key fields from an action set record."""
    entry: dict[str, Any] = {}
    for key in (
        "id",
        "name",
        "status",
        "source",
        "created_at",
        "updated_at",
        "issue_count",
        "action_count",
        "solution_count",
    ):
        val = item.get(key)
        if val is not None:
            entry[key] = val
    return entry


async def list_remediation_action_sets(
    client: AutomoxClient,
    *,
    org_id: int,
) -> dict[str, Any]:
    """List vulnerability remediation action sets."""
    response = await client.get(
        f"/orgs/{org_id}/remediations/action-sets",
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


async def get_action_set_actions(
    client: AutomoxClient,
    *,
    org_id: int,
    action_set_id: int,
) -> dict[str, Any]:
    """Get remediation actions for an action set."""
    response = await client.get(
        f"/orgs/{org_id}/remediations/action-sets/{action_set_id}/actions",
    )

    actions = _extract_list(response)

    return {
        "data": {
            "action_set_id": action_set_id,
            "total_actions": len(actions),
            "actions": actions,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def get_action_set_issues(
    client: AutomoxClient,
    *,
    org_id: int,
    action_set_id: int,
) -> dict[str, Any]:
    """Get vulnerability issues for an action set."""
    response = await client.get(
        f"/orgs/{org_id}/remediations/action-sets/{action_set_id}/issues",
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
) -> dict[str, Any]:
    """Get solutions for an action set."""
    response = await client.get(
        f"/orgs/{org_id}/remediations/action-sets/{action_set_id}/solutions",
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

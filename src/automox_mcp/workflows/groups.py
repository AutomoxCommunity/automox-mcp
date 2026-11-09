"""Server group workflows for Automox MCP."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient
from ..schemas import UI_COLOR_HEX
from ..utils.response import build_pagination_metadata

# refresh_interval is the group's agent check-in / scan cadence. The unit is
# MINUTES (live-verified 2026-06-05: console 24h/4h cadences read back as
# 1440/240). Spec range is 240-1440. The projection keeps the raw integer for
# fidelity; this note travels in metadata.field_notes so the model does not
# mistake the value for seconds/hours.
_REFRESH_INTERVAL_NOTE = (
    "refresh_interval is the group's agent check-in / scan cadence in MINUTES "
    "(live-verified 2026-06-05: console 24h/4h cadences read back as 1440/240). "
    "Spec range: 240-1440. The raw integer is preserved as-is. null means the "
    "organization's devices own their settings: omit refresh_interval when "
    "creating or updating its groups."
)

# Update rules a stored value must still meet to be sent back; the API accepts
# longer notes on create than on update.
_UPDATE_NOTES_MAX_LENGTH = 500
_UPDATE_WSUS_SERVER_MAX_LENGTH = 100
_UI_COLOR_PATTERN = re.compile(UI_COLOR_HEX)


def _summarize_group(group: Mapping[str, Any]) -> dict[str, Any]:
    """Extract key fields from a server group record."""
    return {
        "id": group.get("id"),
        "uuid": group.get("uuid"),
        "name": group.get("name") or "(unnamed)",
        "organization_id": group.get("organization_id"),
        "parent_server_group_id": group.get("parent_server_group_id"),
        "server_count": group.get("server_count", 0),
        "policy_count": len(group.get("policies") or []),
        "policies": group.get("policies"),
        "ui_color": group.get("ui_color"),
        "notes": group.get("notes"),
        "refresh_interval": group.get("refresh_interval"),
    }


def _preserved_group_fields(group: Mapping[str, Any]) -> dict[str, Any]:
    """Return the group's current settable fields that a full-replace PUT would clear.

    A null value is left out: in an organization whose devices own their
    settings the API reads these back as null and rejects a save that sets them.
    """
    preserved: dict[str, Any] = {}
    for field in ("refresh_interval", "enable_os_auto_update", "notes"):
        value = group.get(field)
        if value is not None:
            preserved[field] = value
    if group.get("ui_color"):
        preserved["ui_color"] = group["ui_color"]
    wsus = group.get("wsus_config")
    if isinstance(wsus, Mapping):
        managed = wsus.get("is_managed")
        server = _usable_wsus_server(wsus)
        if server:
            preserved["wsus_server"] = server
        # WSUS on without a usable server is rejected, so such a row is left to reset.
        if managed is False or (managed is True and server):
            preserved["enable_wsus"] = managed
    return preserved


def _usable_wsus_server(wsus: Mapping[str, Any]) -> str:
    """Return the stored WSUS server if an update accepts it, else an empty string."""
    server_url = wsus.get("server_url")
    server = server_url.strip() if isinstance(server_url, str) else ""
    return server if len(server) <= _UPDATE_WSUS_SERVER_MAX_LENGTH else ""


def _wsus_dropped(group: Mapping[str, Any], preserved: Mapping[str, Any]) -> bool:
    """Whether the update resets a stored WSUS setting the caller cannot keep."""
    wsus = group.get("wsus_config")
    if not isinstance(wsus, Mapping):
        return False
    server_url = wsus.get("server_url")
    lost_server = isinstance(server_url, str) and bool(server_url.strip())
    return (wsus.get("is_managed") is True and "enable_wsus" not in preserved) or (
        lost_server and "wsus_server" not in preserved
    )


def _rejected_on_update(preserved: Mapping[str, Any]) -> list[str]:
    """Name the kept ui_color/notes values the update rules reject (not refresh_interval)."""
    rejected: list[str] = []
    color = preserved.get("ui_color")
    if color is not None and not (isinstance(color, str) and _UI_COLOR_PATTERN.fullmatch(color)):
        rejected.append("ui_color")
    if len(preserved.get("notes", "")) > _UPDATE_NOTES_MAX_LENGTH:
        rejected.append("notes")
    return rejected


async def list_server_groups(
    client: AutomoxClient,
    *,
    org_id: int,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List all server groups in the organization."""
    params: dict[str, Any] = {"o": org_id}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit

    groups = await client.get("/servergroups", params=params)

    if not isinstance(groups, list):
        groups = []

    summary = [_summarize_group(g) for g in groups if isinstance(g, Mapping)]

    # /servergroups is a bare list with no upstream total: groups_returned is
    # the page count, not a grand total across all pages.
    normalized_page = page if page is None else max(page, 0)
    has_more = bool(limit is not None and len(summary) >= limit)

    metadata: dict[str, Any] = {
        "deprecated_endpoint": False,
        "field_notes": {"refresh_interval": _REFRESH_INTERVAL_NOTE},
        "pagination": build_pagination_metadata(
            page=normalized_page,
            page_size=limit,
            has_more=has_more,
        ),
    }
    if has_more and normalized_page is not None:
        metadata["suggested_next_call"] = {
            "tool": "list_server_groups",
            "args": {"org_id": org_id, "page": normalized_page + 1, "limit": limit},
        }

    return {
        "data": {
            "groups_returned": len(summary),
            "groups": summary,
        },
        "metadata": metadata,
    }


async def get_server_group(
    client: AutomoxClient,
    *,
    org_id: int,
    group_id: int,
) -> dict[str, Any]:
    """Retrieve details for a specific server group."""
    params: dict[str, Any] = {"o": org_id}
    group = await client.get(f"/servergroups/{group_id}", params=params)

    data: dict[str, Any]
    if isinstance(group, Mapping):
        data = _summarize_group(group)
    else:
        data = {"group_id": group_id, "raw": group}

    return {
        "data": data,
        "metadata": {
            "deprecated_endpoint": False,
            "field_notes": {"refresh_interval": _REFRESH_INTERVAL_NOTE},
        },
    }


async def create_server_group(
    client: AutomoxClient,
    *,
    org_id: int,
    name: str,
    refresh_interval: int | None = None,
    parent_server_group_id: int | None = None,
    ui_color: str | None = None,
    notes: str | None = None,
    policies: list | None = None,
) -> dict[str, Any]:
    """Create a new server group."""
    body: dict[str, Any] = {"name": name}
    if refresh_interval is not None:
        body["refresh_interval"] = refresh_interval
    if parent_server_group_id is not None:
        body["parent_server_group_id"] = parent_server_group_id
    if ui_color is not None:
        body["ui_color"] = ui_color
    if notes is not None:
        body["notes"] = notes
    if policies is not None:
        body["policies"] = policies

    params: dict[str, Any] = {"o": org_id}
    result = await client.post("/servergroups", json_data=body, params=params)

    data: dict[str, Any]
    if isinstance(result, Mapping):
        data = _summarize_group(result)
        data["created"] = True
    else:
        data = {"name": name, "created": True, "raw": result}

    return {
        "data": data,
        "metadata": {
            "deprecated_endpoint": False,
            "field_notes": {"refresh_interval": _REFRESH_INTERVAL_NOTE},
        },
    }


async def update_server_group(
    client: AutomoxClient,
    *,
    org_id: int,
    group_id: int,
    name: str,
    refresh_interval: int | None = None,
    parent_server_group_id: int | None = None,
    ui_color: str | None = None,
    notes: str | None = None,
    policies: list | None = None,
) -> dict[str, Any]:
    """Update an existing server group.

    The API replaces the whole group, so fields the caller leaves unset are
    filled from the group's current values instead of being cleared.
    """
    params: dict[str, Any] = {"o": org_id}
    current = await client.get(f"/servergroups/{group_id}", params=params)
    if not isinstance(current, Mapping) or current.get("id") is None:
        raise ValueError(
            f"Could not read server group {group_id} to keep its current settings; "
            "the group was not updated."
        )
    body = _preserved_group_fields(current)
    caller_set = {"ui_color": ui_color, "notes": notes}
    rejected = [f for f in _rejected_on_update(body) if caller_set.get(f) is None]
    if rejected:
        raise ValueError(
            f"Server group {group_id} holds a value an update does not accept for "
            f"{', '.join(rejected)}; pass {'it' if len(rejected) == 1 else 'them'} "
            "explicitly (ui_color #RRGGBB or an empty string to clear, notes at "
            f"most {_UPDATE_NOTES_MAX_LENGTH} characters)."
        )
    wsus_reset = _wsus_dropped(current, body)

    body["name"] = name
    if refresh_interval is not None:
        body["refresh_interval"] = refresh_interval
    if parent_server_group_id is not None:
        body["parent_server_group_id"] = parent_server_group_id
    if ui_color is not None:
        body["ui_color"] = ui_color or None
    if notes is not None:
        body["notes"] = notes
    if policies is not None:
        body["policies"] = policies

    await client.put(f"/servergroups/{group_id}", json_data=body, params=params)

    # The API answers an update with 204, so report the state that was sent.
    data = _summarize_group({**current, **body, "id": group_id})
    data["updated"] = True

    metadata: dict[str, Any] = {
        "deprecated_endpoint": False,
        "field_notes": {"refresh_interval": _REFRESH_INTERVAL_NOTE},
    }
    if wsus_reset:
        metadata["warnings"] = [
            "This group's WSUS setting is reset unless its organization's devices own "
            "their settings: its stored WSUS server is blank or longer than the 100 "
            "characters an update accepts, and this tool cannot set WSUS."
        ]
    return {"data": data, "metadata": metadata}


async def delete_server_group(
    client: AutomoxClient,
    *,
    org_id: int,
    group_id: int,
) -> dict[str, Any]:
    """Delete a server group."""
    params: dict[str, Any] = {"o": org_id}
    await client.delete(f"/servergroups/{group_id}", params=params)

    return {
        "data": {
            "group_id": group_id,
            "deleted": True,
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }

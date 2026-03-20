"""Tests for server group workflows."""

import copy
from typing import Any, cast

import pytest

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.groups import (
    create_server_group,
    delete_server_group,
    get_server_group,
    list_server_groups,
    update_server_group,
)


# ---------------------------------------------------------------------------
# Stub client
# ---------------------------------------------------------------------------


class StubClient:
    """Minimal client stub that records calls and returns canned responses."""

    def __init__(
        self,
        *,
        get_responses: dict[str, list[Any]] | None = None,
        post_responses: dict[str, list[Any]] | None = None,
        put_responses: dict[str, list[Any]] | None = None,
        delete_responses: dict[str, list[Any]] | None = None,
    ) -> None:
        self._get = {k: list(v) for k, v in (get_responses or {}).items()}
        self._post = {k: list(v) for k, v in (post_responses or {}).items()}
        self._put = {k: list(v) for k, v in (put_responses or {}).items()}
        self._delete = {k: list(v) for k, v in (delete_responses or {}).items()}
        self.calls: list[tuple[str, str, Any]] = []

    async def get(self, path, *, params=None, headers=None):
        self.calls.append(("GET", path, params))
        responses = self._get.get(path)
        return copy.deepcopy(responses.pop(0)) if responses else {}

    async def post(self, path, *, json_data=None, params=None, headers=None):
        self.calls.append(("POST", path, json_data))
        responses = self._post.get(path)
        return copy.deepcopy(responses.pop(0)) if responses else {}

    async def put(self, path, *, json_data=None, params=None, headers=None):
        self.calls.append(("PUT", path, json_data))
        responses = self._put.get(path)
        return copy.deepcopy(responses.pop(0)) if responses else {}

    async def delete(self, path, *, params=None, headers=None):
        self.calls.append(("DELETE", path, params))
        responses = self._delete.get(path)
        return copy.deepcopy(responses.pop(0)) if responses else None


_GROUP_A: dict[str, Any] = {
    "id": 10,
    "name": "Production",
    "organization_id": 555,
    "parent_server_group_id": 0,
    "server_count": 25,
    "policies": [301, 302],
    "ui_color": "#FF0000",
    "notes": "Prod servers",
    "refresh_interval": 360,
}

_GROUP_B: dict[str, Any] = {
    "id": 20,
    "name": "Staging",
    "organization_id": 555,
    "parent_server_group_id": 0,
    "server_count": 5,
    "policies": [301],
    "ui_color": None,
    "notes": None,
    "refresh_interval": 720,
}


# ---------------------------------------------------------------------------
# list_server_groups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_groups_returns_summaries() -> None:
    client = StubClient(get_responses={"/servergroups": [[_GROUP_A, _GROUP_B]]})
    result = await list_server_groups(cast(AutomoxClient, client), org_id=555)

    assert result["data"]["total_groups"] == 2
    names = [g["name"] for g in result["data"]["groups"]]
    assert "Production" in names
    assert "Staging" in names


@pytest.mark.asyncio
async def test_list_groups_passes_pagination() -> None:
    client = StubClient(get_responses={"/servergroups": [[_GROUP_A]]})
    await list_server_groups(cast(AutomoxClient, client), org_id=555, page=2, limit=10)

    params = client.calls[0][2]
    assert params["page"] == 2
    assert params["limit"] == 10
    assert params["o"] == 555


@pytest.mark.asyncio
async def test_list_groups_handles_non_list_response() -> None:
    client = StubClient(get_responses={"/servergroups": ["unexpected"]})
    result = await list_server_groups(cast(AutomoxClient, client), org_id=555)
    assert result["data"]["total_groups"] == 0


@pytest.mark.asyncio
async def test_list_groups_extracts_policy_count() -> None:
    client = StubClient(get_responses={"/servergroups": [[_GROUP_A]]})
    result = await list_server_groups(cast(AutomoxClient, client), org_id=555)

    group = result["data"]["groups"][0]
    assert group["policy_count"] == 2
    assert group["server_count"] == 25


# ---------------------------------------------------------------------------
# get_server_group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_group_returns_detail() -> None:
    client = StubClient(get_responses={"/servergroups/10": [_GROUP_A]})
    result = await get_server_group(cast(AutomoxClient, client), org_id=555, group_id=10)

    assert result["data"]["name"] == "Production"
    assert result["data"]["refresh_interval"] == 360


@pytest.mark.asyncio
async def test_get_group_unnamed_fallback() -> None:
    unnamed = {**_GROUP_A, "name": None}
    client = StubClient(get_responses={"/servergroups/10": [unnamed]})
    result = await get_server_group(cast(AutomoxClient, client), org_id=555, group_id=10)

    assert result["data"]["name"] == "(unnamed)"


# ---------------------------------------------------------------------------
# create_server_group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_group_returns_created_flag() -> None:
    client = StubClient(post_responses={"/servergroups": [_GROUP_A]})
    result = await create_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        name="Production",
        refresh_interval=360,
        parent_server_group_id=0,
    )

    assert result["data"]["created"] is True
    assert result["data"]["name"] == "Production"


@pytest.mark.asyncio
async def test_create_group_sends_optional_fields() -> None:
    client = StubClient(post_responses={"/servergroups": [_GROUP_A]})
    await create_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        name="Production",
        refresh_interval=360,
        parent_server_group_id=0,
        ui_color="#FF0000",
        notes="Prod servers",
        policies=[301, 302],
    )

    body = client.calls[0][2]
    assert body["ui_color"] == "#FF0000"
    assert body["notes"] == "Prod servers"
    assert body["policies"] == [301, 302]


@pytest.mark.asyncio
async def test_create_group_omits_none_optionals() -> None:
    client = StubClient(post_responses={"/servergroups": [_GROUP_A]})
    await create_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        name="Production",
        refresh_interval=360,
    )

    body = client.calls[0][2]
    assert "ui_color" not in body
    assert "notes" not in body
    assert "policies" not in body


# ---------------------------------------------------------------------------
# update_server_group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_group_returns_updated_flag() -> None:
    updated = {**_GROUP_A, "name": "Production-v2"}
    client = StubClient(put_responses={"/servergroups/10": [updated]})
    result = await update_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        group_id=10,
        name="Production-v2",
        refresh_interval=360,
    )

    assert result["data"]["updated"] is True
    assert result["data"]["name"] == "Production-v2"


@pytest.mark.asyncio
async def test_update_group_sends_body_to_correct_path() -> None:
    client = StubClient(put_responses={"/servergroups/10": [_GROUP_A]})
    await update_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        group_id=10,
        name="Production",
        refresh_interval=720,
    )

    assert client.calls[0][0] == "PUT"
    assert client.calls[0][1] == "/servergroups/10"
    body = client.calls[0][2]
    assert body["refresh_interval"] == 720


# ---------------------------------------------------------------------------
# delete_server_group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_group_returns_confirmation() -> None:
    client = StubClient()
    result = await delete_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=10,
    )

    assert result["data"]["deleted"] is True
    assert result["data"]["group_id"] == 10
    assert client.calls[0] == ("DELETE", "/servergroups/10", {"o": 555})

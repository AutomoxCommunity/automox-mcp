"""Tests for server group workflows."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxAPIError, AutomoxClient
from automox_mcp.utils.group_rules import UPDATE_WSUS_SERVER_MAX_LENGTH
from automox_mcp.workflows.groups import (
    create_server_group,
    delete_server_group,
    get_server_group,
    list_server_groups,
    update_server_group,
)

_GROUP_A: dict[str, Any] = {
    "id": 10,
    "name": "Production",
    "organization_id": 555,
    "parent_server_group_id": 0,
    "server_count": 25,
    "policies": [301, 302],
    "ui_color": "#FF0000",
    "notes": "Prod servers",
    # 1440 = console 24h scan cadence (live-observed minute value, 2026-06-05).
    "refresh_interval": 1440,
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
    # 240 = console 4h scan cadence (live-observed minute value, 2026-06-05).
    "refresh_interval": 240,
}


# ---------------------------------------------------------------------------
# list_server_groups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_groups_returns_summaries() -> None:
    client = StubClient(get_responses={"/servergroups": [[_GROUP_A, _GROUP_B]]})
    result = await list_server_groups(cast(AutomoxClient, client), org_id=555)

    assert result["data"]["groups_returned"] == 2
    names = [g["name"] for g in result["data"]["groups"]]
    assert "Production" in names
    assert "Staging" in names

    # refresh_interval legend present and stating the unit; raw integers preserved.
    note = result["metadata"]["field_notes"]["refresh_interval"]
    assert "minute" in note.lower()
    intervals = {g["refresh_interval"] for g in result["data"]["groups"]}
    assert intervals == {1440, 240}


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
    assert result["data"]["groups_returned"] == 0


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
    assert result["data"]["refresh_interval"] == 1440
    # get_server_group carries the same minutes legend.
    note = result["metadata"]["field_notes"]["refresh_interval"]
    assert "minute" in note.lower()


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
        refresh_interval=1440,
        parent_server_group_id=0,
    )

    assert result["data"]["created"] is True
    assert result["data"]["name"] == "Production"
    # refresh_interval round-trips unchanged (no unit transformation introduced).
    assert client.calls[0][2]["refresh_interval"] == 1440
    assert result["data"]["refresh_interval"] == 1440
    assert "minute" in result["metadata"]["field_notes"]["refresh_interval"].lower()


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
    # PUT returns 204, which the client reads as an empty dict.
    client = StubClient(
        get_responses={"/servergroups/30": [_GROUP_OWNED_LIVE]},
        put_responses={"/servergroups/30": [{}]},
    )
    result = await update_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        group_id=30,
        name="Workstations-v2",
        refresh_interval=360,
    )

    data = result["data"]
    assert data["updated"] is True
    assert data["id"] == 30
    assert data["name"] == "Workstations-v2"
    assert data["refresh_interval"] == 360
    assert data["ui_color"] == "#CC0000"
    assert data["policies"] == [301, 302]


@pytest.mark.asyncio
async def test_update_group_sends_body_to_correct_path() -> None:
    client = StubClient(
        get_responses={"/servergroups/30": [_GROUP_OWNED_LIVE]},
        put_responses={"/servergroups/30": [{}]},
    )
    result = await update_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        group_id=30,
        name="Workstations",
        refresh_interval=240,
    )

    assert client.calls[1][0] == "PUT"
    assert client.calls[1][1] == "/servergroups/30"
    body = client.calls[1][2]
    # refresh_interval round-trips unchanged (no unit transformation introduced).
    assert body["refresh_interval"] == 240
    assert "minute" in result["metadata"]["field_notes"]["refresh_interval"].lower()


# GET /servergroups/{id} shapes captured from the live API, with identifiers,
# text and setting values replaced. In a group-owned organization the group
# carries its settings; where devices own their settings they read back as null.
_GROUP_OWNED_LIVE: dict[str, Any] = {
    "id": 30,
    "uuid": "00000000-0000-0000-0000-000000000030",
    "name": "Workstations",
    "organization_id": 555,
    "parent_server_group_id": 1,
    "server_count": 3,
    "policies": [301, 302],
    "ui_color": "#CC0000",
    "notes": "Office laptops",
    "refresh_interval": 240,
    "enable_os_auto_update": True,
    "wsus_config": {
        "id": 70,
        "server_group_id": 30,
        "is_managed": True,
        "server_url": "https://wsus.example.com:8531",
        "created_at": "2025-12-09T01:01:53+0000",
        "updated_at": "2025-12-09T01:01:53+0000",
    },
}

_DEVICE_OWNED_LIVE: dict[str, Any] = {
    "id": 40,
    "uuid": "00000000-0000-0000-0000-000000000040",
    "name": "Default Group",
    "organization_id": 555,
    "parent_server_group_id": 40,
    "server_count": 10,
    "policies": [301],
    "ui_color": "#059F1D",
    "notes": "",
    "refresh_interval": None,
    "enable_os_auto_update": None,
    "wsus_config": None,
}


@pytest.mark.asyncio
async def test_update_group_preserves_unset_fields() -> None:
    client = StubClient(get_responses={"/servergroups/30": [_GROUP_OWNED_LIVE]})
    result = await update_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        group_id=30,
        name="Laptops",
        parent_server_group_id=1,
    )

    assert "warnings" not in result["metadata"]

    assert client.calls[0] == ("GET", "/servergroups/30", {"o": 555})
    method, path, body = client.calls[1]
    assert (method, path) == ("PUT", "/servergroups/30")
    assert body == {
        "name": "Laptops",
        "parent_server_group_id": 1,
        "refresh_interval": 240,
        "ui_color": "#CC0000",
        "notes": "Office laptops",
        "policies": [301, 302],
        "enable_os_auto_update": True,
        "enable_wsus": True,
        "wsus_server": "https://wsus.example.com:8531",
    }


@pytest.mark.asyncio
async def test_update_group_keeps_parent_when_caller_leaves_it_unset() -> None:
    client = StubClient(get_responses={"/servergroups/30": [_GROUP_OWNED_LIVE]})
    result = await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Laptops"
    )

    assert client.calls[1][2]["parent_server_group_id"] == 1
    assert result["data"]["parent_server_group_id"] == 1


@pytest.mark.asyncio
async def test_update_group_without_any_parent_asks_for_one() -> None:
    group = {**_GROUP_OWNED_LIVE, "parent_server_group_id": None}
    client = StubClient(get_responses={"/servergroups/30": [group]})
    with pytest.raises(ValueError, match="no stored parent group.*pass parent_server_group_id"):
        await update_server_group(
            cast(AutomoxClient, client), org_id=555, group_id=30, name="Laptops"
        )

    assert [c[0] for c in client.calls] == ["GET"]


@pytest.mark.asyncio
async def test_update_group_caller_parent_covers_missing_stored_parent() -> None:
    group = {**_GROUP_OWNED_LIVE, "parent_server_group_id": None}
    client = StubClient(get_responses={"/servergroups/30": [group]})
    await update_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        group_id=30,
        name="Laptops",
        parent_server_group_id=7,
    )

    assert client.calls[1][2]["parent_server_group_id"] == 7


@pytest.mark.asyncio
async def test_update_group_missing_stored_policies_are_not_sent() -> None:
    group = {k: v for k, v in _GROUP_OWNED_LIVE.items() if k != "policies"}
    client = StubClient(get_responses={"/servergroups/30": [group]})
    await update_server_group(cast(AutomoxClient, client), org_id=555, group_id=30, name="Laptops")

    assert "policies" not in client.calls[1][2]


@pytest.mark.asyncio
async def test_update_group_stored_empty_policies_go_back_empty() -> None:
    group = {**_GROUP_OWNED_LIVE, "policies": []}
    client = StubClient(get_responses={"/servergroups/30": [group]})
    await update_server_group(cast(AutomoxClient, client), org_id=555, group_id=30, name="Laptops")

    assert client.calls[1][2]["policies"] == []


@pytest.mark.parametrize("notes", [42, ["a"], {"text": "a"}])
@pytest.mark.asyncio
async def test_update_group_non_text_stored_notes_need_explicit_notes(notes: Any) -> None:
    group = {**_GROUP_OWNED_LIVE, "notes": notes}
    client = StubClient(get_responses={"/servergroups/30": [group]})
    with pytest.raises(ValueError, match="notes: the stored notes are not text"):
        await update_server_group(
            cast(AutomoxClient, client), org_id=555, group_id=30, name="Laptops"
        )

    assert [c[0] for c in client.calls] == ["GET"]


@pytest.mark.asyncio
async def test_update_group_non_text_stored_notes_replaced_by_caller() -> None:
    group = {**_GROUP_OWNED_LIVE, "notes": 42}
    client = StubClient(get_responses={"/servergroups/30": [group]})
    await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Laptops", notes=""
    )

    assert client.calls[1][2]["notes"] == ""


@pytest.mark.asyncio
async def test_update_group_caller_values_override_current() -> None:
    client = StubClient(get_responses={"/servergroups/30": [_GROUP_OWNED_LIVE]})
    await update_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        group_id=30,
        name="Workstations",
        refresh_interval=1440,
        parent_server_group_id=1,
        ui_color="#00FF00",
        notes="",
        policies=[301],
    )

    body = client.calls[1][2]
    assert body["refresh_interval"] == 1440
    assert body["ui_color"] == "#00FF00"
    assert body["notes"] == ""
    assert body["policies"] == [301]
    assert body["enable_wsus"] is True


@pytest.mark.asyncio
async def test_update_group_device_owned_sends_no_settings() -> None:
    client = StubClient(get_responses={"/servergroups/40": [_DEVICE_OWNED_LIVE]})
    await update_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        group_id=40,
        name="Default Group",
        parent_server_group_id=40,
        policies=[301, 302],
    )

    body = client.calls[1][2]
    assert body == {
        "name": "Default Group",
        "parent_server_group_id": 40,
        "ui_color": "#059F1D",
        "notes": "",
        "policies": [301, 302],
    }


@pytest.mark.asyncio
async def test_update_group_wsus_row_without_setting_is_not_sent() -> None:
    group = {
        **_GROUP_OWNED_LIVE,
        "wsus_config": {**_GROUP_OWNED_LIVE["wsus_config"], "is_managed": None, "server_url": None},
    }
    client = StubClient(get_responses={"/servergroups/30": [group]})
    await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
    )

    body = client.calls[1][2]
    assert "enable_wsus" not in body
    assert "wsus_server" not in body


@pytest.mark.asyncio
async def test_update_group_wsus_off_keeps_server_without_url() -> None:
    group = {
        **_GROUP_OWNED_LIVE,
        "wsus_config": {
            **_GROUP_OWNED_LIVE["wsus_config"],
            "is_managed": False,
            "server_url": None,
        },
    }
    client = StubClient(get_responses={"/servergroups/30": [group]})
    result = await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
    )

    body = client.calls[1][2]
    assert body["enable_wsus"] is False
    assert "wsus_server" not in body
    assert "warnings" not in result["metadata"]


@pytest.mark.asyncio
async def test_update_group_wsus_off_keeps_stored_server() -> None:
    group = {
        **_GROUP_OWNED_LIVE,
        "wsus_config": {**_GROUP_OWNED_LIVE["wsus_config"], "is_managed": False},
    }
    client = StubClient(get_responses={"/servergroups/30": [group]})
    result = await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
    )

    body = client.calls[1][2]
    assert body["enable_wsus"] is False
    assert body["wsus_server"] == "https://wsus.example.com:8531"
    assert "warnings" not in result["metadata"]


@pytest.mark.asyncio
async def test_update_group_wsus_unset_keeps_stored_server() -> None:
    group = {
        **_GROUP_OWNED_LIVE,
        "wsus_config": {**_GROUP_OWNED_LIVE["wsus_config"], "is_managed": None},
    }
    client = StubClient(get_responses={"/servergroups/30": [group]})
    result = await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
    )

    body = client.calls[1][2]
    assert "enable_wsus" not in body
    assert body["wsus_server"] == "https://wsus.example.com:8531"
    assert "warnings" not in result["metadata"]


@pytest.mark.asyncio
async def test_update_group_wsus_server_at_limit_is_kept() -> None:
    server = "h" * UPDATE_WSUS_SERVER_MAX_LENGTH
    group = {
        **_GROUP_OWNED_LIVE,
        "wsus_config": {**_GROUP_OWNED_LIVE["wsus_config"], "server_url": server},
    }
    client = StubClient(get_responses={"/servergroups/30": [group]})
    result = await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
    )

    body = client.calls[1][2]
    assert body["enable_wsus"] is True
    assert body["wsus_server"] == server
    assert "warnings" not in result["metadata"]


@pytest.mark.asyncio
async def test_update_group_wsus_off_server_over_limit_warns() -> None:
    group = {
        **_GROUP_OWNED_LIVE,
        "wsus_config": {
            **_GROUP_OWNED_LIVE["wsus_config"],
            "is_managed": False,
            "server_url": "h" * 101,
        },
    }
    client = StubClient(get_responses={"/servergroups/30": [group]})
    result = await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
    )

    body = client.calls[1][2]
    assert body["enable_wsus"] is False
    assert "wsus_server" not in body
    assert "WSUS setting was reset" in result["metadata"]["warnings"][0]


@pytest.mark.asyncio
async def test_update_group_keeps_stored_false_os_auto_update() -> None:
    group = {**_GROUP_OWNED_LIVE, "enable_os_auto_update": False}
    client = StubClient(get_responses={"/servergroups/30": [group]})
    await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
    )

    assert client.calls[1][2]["enable_os_auto_update"] is False


@pytest.mark.asyncio
async def test_update_group_device_owned_refusal_propagates() -> None:
    client = StubClient(get_responses={"/servergroups/40": [_DEVICE_OWNED_LIVE]})
    refusal = {
        "errors": [
            "This organization's devices own their settings, so a group save cannot "
            "set them: refresh_interval. Use the Device Settings API instead."
        ],
        "code": "DEVICE_OWNED_SETTINGS",
    }

    async def _raise(path: str, *, json_data: Any = None, **kw: Any) -> Any:
        client.calls.append(("PUT", path, json_data))
        raise AutomoxAPIError("automox API error", status_code=422, payload=refusal)

    client.put = _raise  # type: ignore[assignment]
    with pytest.raises(AutomoxAPIError) as excinfo:
        await update_server_group(
            cast(AutomoxClient, client),
            org_id=555,
            group_id=40,
            name="Default Group",
            refresh_interval=720,
        )

    assert excinfo.value.payload["code"] == "DEVICE_OWNED_SETTINGS"
    assert [c[0] for c in client.calls] == ["GET", "PUT"]
    assert client.calls[1][2]["refresh_interval"] == 720


@pytest.mark.asyncio
async def test_update_group_read_failure_sends_no_put() -> None:
    client = StubClient()

    async def _raise(*a: Any, **kw: Any) -> Any:
        raise AutomoxAPIError("not found", status_code=404)

    client.get = _raise  # type: ignore[assignment]
    with pytest.raises(AutomoxAPIError, match="not found"):
        await update_server_group(
            cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
        )

    assert client.calls == []


@pytest.mark.parametrize("current", [{}, [], None])
@pytest.mark.asyncio
async def test_update_group_unreadable_group_sends_no_put(current: Any) -> None:
    client = StubClient(get_responses={"/servergroups/30": [current]})
    with pytest.raises(ValueError, match="was not updated"):
        await update_server_group(
            cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
        )

    assert [c[0] for c in client.calls] == ["GET"]


@pytest.mark.asyncio
async def test_update_group_long_stored_notes_need_explicit_notes() -> None:
    group = {**_GROUP_OWNED_LIVE, "notes": "n" * 501}
    client = StubClient(get_responses={"/servergroups/30": [group]})
    with pytest.raises(ValueError) as excinfo:
        await update_server_group(
            cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
        )

    message = str(excinfo.value)
    assert "was not updated" in message
    assert "notes: the stored notes are 501 characters" in message
    assert "or an empty string to clear them" in message
    assert "ui_color" not in message
    assert [c[0] for c in client.calls] == ["GET"]


@pytest.mark.asyncio
async def test_update_group_long_stored_notes_replaced_by_caller() -> None:
    group = {**_GROUP_OWNED_LIVE, "notes": "n" * 501}
    client = StubClient(get_responses={"/servergroups/30": [group]})
    await update_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        group_id=30,
        name="Workstations",
        notes="short",
    )

    assert client.calls[1][2]["notes"] == "short"


@pytest.mark.asyncio
async def test_update_group_stored_notes_at_limit_are_kept() -> None:
    group = {**_GROUP_OWNED_LIVE, "notes": "n" * 500}
    client = StubClient(get_responses={"/servergroups/30": [group]})
    await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
    )

    assert client.calls[1][2]["notes"] == "n" * 500


@pytest.mark.asyncio
async def test_update_group_stored_color_update_rejects_needs_caller_value() -> None:
    client = StubClient(
        get_responses={"/servergroups/30": [{**_GROUP_OWNED_LIVE, "ui_color": "#FFF"}]}
    )
    with pytest.raises(ValueError, match="ui_color: the stored color is not #RRGGBB"):
        await update_server_group(
            cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
        )

    assert [c[0] for c in client.calls] == ["GET"]


@pytest.mark.asyncio
async def test_update_group_names_every_stored_value_update_rejects() -> None:
    group = {**_GROUP_OWNED_LIVE, "ui_color": "#FFF", "notes": "n" * 501}
    client = StubClient(get_responses={"/servergroups/30": [group]})
    with pytest.raises(ValueError) as excinfo:
        await update_server_group(
            cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
        )

    message = str(excinfo.value)
    assert "ui_color: the stored color" in message
    assert "notes: the stored notes are 501 characters" in message

    assert [c[0] for c in client.calls] == ["GET"]


@pytest.mark.parametrize(
    ("caller", "still_rejected"),
    [({"ui_color": "#00FF00"}, "notes"), ({"notes": "ok"}, "ui_color")],
)
@pytest.mark.asyncio
async def test_update_group_names_only_stored_values_caller_left_unset(
    caller: dict[str, Any], still_rejected: str
) -> None:
    group = {**_GROUP_OWNED_LIVE, "ui_color": "#FFF", "notes": "n" * 501}
    client = StubClient(get_responses={"/servergroups/30": [group]})
    with pytest.raises(ValueError) as excinfo:
        await update_server_group(
            cast(AutomoxClient, client),
            org_id=555,
            group_id=30,
            name="Workstations",
            **caller,
        )

    message = str(excinfo.value)
    assert f"{still_rejected}: the stored" in message
    assert f"{next(iter(caller))}: the stored" not in message

    assert [c[0] for c in client.calls] == ["GET"]


@pytest.mark.parametrize("interval", [60, 10080])
@pytest.mark.asyncio
async def test_update_group_stored_interval_goes_back_unchanged(interval: int) -> None:
    group = {**_GROUP_OWNED_LIVE, "refresh_interval": interval}
    client = StubClient(get_responses={"/servergroups/30": [group]})
    await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
    )

    assert client.calls[1][2]["refresh_interval"] == interval


@pytest.mark.asyncio
async def test_update_group_stored_empty_color_is_not_sent() -> None:
    group = {**_GROUP_OWNED_LIVE, "ui_color": ""}
    client = StubClient(get_responses={"/servergroups/30": [group]})
    await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
    )

    assert "ui_color" not in client.calls[1][2]


@pytest.mark.asyncio
async def test_update_group_caller_replaces_stored_values_update_rejects() -> None:
    group = {**_GROUP_OWNED_LIVE, "ui_color": "#FFF", "notes": "n" * 501}
    client = StubClient(get_responses={"/servergroups/30": [group]})
    await update_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        group_id=30,
        name="Workstations",
        ui_color="",
        notes="",
    )

    body = client.calls[1][2]
    assert body["ui_color"] is None
    assert body["notes"] == ""


@pytest.mark.asyncio
async def test_update_group_empty_ui_color_clears_it() -> None:
    client = StubClient(get_responses={"/servergroups/30": [_GROUP_OWNED_LIVE]})
    result = await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations", ui_color=""
    )

    assert client.calls[1][2]["ui_color"] is None
    assert result["data"]["ui_color"] is None


@pytest.mark.asyncio
async def test_update_group_wsus_server_over_limit_is_not_sent() -> None:
    group = {
        **_GROUP_OWNED_LIVE,
        "wsus_config": {**_GROUP_OWNED_LIVE["wsus_config"], "server_url": "h" * 101},
    }
    client = StubClient(get_responses={"/servergroups/30": [group]})
    result = await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
    )

    body = client.calls[1][2]
    assert "enable_wsus" not in body
    assert "wsus_server" not in body
    warning = result["metadata"]["warnings"][0]
    assert "WSUS setting was reset" in warning
    assert f"longer than the {UPDATE_WSUS_SERVER_MAX_LENGTH} characters" in warning


@pytest.mark.asyncio
async def test_update_group_device_owned_result_reads_settings_as_null() -> None:
    client = StubClient(
        get_responses={"/servergroups/40": [_DEVICE_OWNED_LIVE]},
        put_responses={"/servergroups/40": [{}]},
    )
    result = await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=40, name="All Devices"
    )

    assert result["data"]["name"] == "All Devices"
    assert result["data"]["refresh_interval"] is None


@pytest.mark.asyncio
async def test_update_group_device_owned_result_ignores_sent_interval() -> None:
    client = StubClient(
        get_responses={"/servergroups/40": [_DEVICE_OWNED_LIVE]},
        put_responses={"/servergroups/40": [{}]},
    )
    result = await update_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        group_id=40,
        name="All Devices",
        refresh_interval=1440,
    )

    assert client.calls[1][2]["refresh_interval"] == 1440
    assert result["data"]["refresh_interval"] is None


@pytest.mark.asyncio
async def test_update_group_wsus_on_without_server_is_not_sent() -> None:
    group = {
        **_GROUP_OWNED_LIVE,
        "wsus_config": {**_GROUP_OWNED_LIVE["wsus_config"], "server_url": "  "},
    }
    client = StubClient(get_responses={"/servergroups/30": [group]})
    result = await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
    )

    body = client.calls[1][2]
    assert "enable_wsus" not in body
    assert "wsus_server" not in body
    assert "WSUS setting was reset" in result["metadata"]["warnings"][0]


@pytest.mark.parametrize("server_url", ["", "  "])
@pytest.mark.asyncio
async def test_update_group_wsus_off_with_blank_server_sends_off_only(server_url: str) -> None:
    group = {
        **_GROUP_OWNED_LIVE,
        "wsus_config": {
            **_GROUP_OWNED_LIVE["wsus_config"],
            "is_managed": False,
            "server_url": server_url,
        },
    }
    client = StubClient(get_responses={"/servergroups/30": [group]})
    result = await update_server_group(
        cast(AutomoxClient, client), org_id=555, group_id=30, name="Workstations"
    )

    body = client.calls[1][2]
    assert body["enable_wsus"] is False
    assert "wsus_server" not in body
    assert "warnings" not in result["metadata"]


@pytest.mark.asyncio
async def test_create_group_without_refresh_interval_omits_it() -> None:
    # Only the request body is under test.
    client = StubClient(post_responses={"/servergroups": [{}]})
    await create_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        name="Kiosks",
        parent_server_group_id=40,
    )

    body = client.calls[0][2]
    assert body == {"name": "Kiosks", "parent_server_group_id": 40}


# ---------------------------------------------------------------------------
# delete_server_group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_group_returns_confirmation() -> None:
    client = StubClient()
    result = await delete_server_group(
        cast(AutomoxClient, client),
        org_id=555,
        group_id=10,
    )

    assert result["data"]["deleted"] is True
    assert result["data"]["group_id"] == 10
    assert client.calls[0] == ("DELETE", "/servergroups/10", {"o": 555})


# ---------------------------------------------------------------------------
# Non-Mapping API responses (else branches)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_server_group_non_mapping_response() -> None:
    """When API returns a non-Mapping, fallback raw data is used."""
    client = StubClient(get_responses={"/servergroups/99": [None]})
    result = await get_server_group(cast(AutomoxClient, client), org_id=1, group_id=99)
    assert result["data"]["group_id"] == 99
    assert result["data"]["raw"] is None


@pytest.mark.asyncio
async def test_create_server_group_non_mapping_response() -> None:
    """When create API returns a non-Mapping, fallback includes name and created=True."""
    client = StubClient(post_responses={"/servergroups": ["created-ok"]})
    result = await create_server_group(
        cast(AutomoxClient, client),
        org_id=1,
        name="My Group",
        refresh_interval=360,
    )
    assert result["data"]["name"] == "My Group"
    assert result["data"]["created"] is True


@pytest.mark.asyncio
async def test_update_server_group_non_mapping_response() -> None:
    """A non-Mapping update response reports the state that was sent."""
    client = StubClient(
        get_responses={"/servergroups/5": [{**_GROUP_OWNED_LIVE, "id": 5}]},
        put_responses={"/servergroups/5": ["ok"]},
    )
    result = await update_server_group(
        cast(AutomoxClient, client),
        org_id=1,
        group_id=5,
        name="Updated",
        refresh_interval=720,
    )
    assert result["data"]["id"] == 5
    assert result["data"]["name"] == "Updated"
    assert result["data"]["updated"] is True


@pytest.mark.asyncio
async def test_create_server_group_with_optional_fields() -> None:
    """Optional fields (ui_color, notes, policies) are included in body when set."""
    client = StubClient(
        post_responses={
            "/servergroups": [
                {
                    "id": 20,
                    "name": "Colored Group",
                    "organization_id": 1,
                    "server_count": 0,
                    "policies": [1, 2],
                }
            ]
        }
    )
    result = await create_server_group(
        cast(AutomoxClient, client),
        org_id=1,
        name="Colored Group",
        refresh_interval=360,
        ui_color="#FF0000",
        notes="test notes",
        policies=[1, 2],
    )
    body = client.calls[0][2]
    assert body["ui_color"] == "#FF0000"
    assert body["notes"] == "test notes"
    assert body["policies"] == [1, 2]
    assert result["data"]["name"] == "Colored Group"


@pytest.mark.asyncio
async def test_update_server_group_with_optional_fields() -> None:
    """Optional fields are included in update body when set."""
    client = StubClient(
        get_responses={"/servergroups/30": [_GROUP_OWNED_LIVE]},
        put_responses={"/servergroups/30": [{}]},
    )
    result = await update_server_group(
        cast(AutomoxClient, client),
        org_id=1,
        group_id=30,
        name="Updated",
        refresh_interval=720,
        ui_color="#00FF00",
        notes="updated",
        policies=[],
    )
    body = client.calls[1][2]
    assert body["ui_color"] == "#00FF00"
    assert body["notes"] == "updated"
    assert result["data"]["updated"] is True


# ---------------------------------------------------------------------------
# Error path tests — API errors propagate through the workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_server_groups_api_error_propagates():
    """AutomoxAPIError from the client must not be swallowed."""
    client = StubClient()

    async def _raise(*a: Any, **kw: Any) -> Any:
        raise AutomoxAPIError("forbidden", status_code=403)

    client.get = _raise  # type: ignore[assignment]
    with pytest.raises(AutomoxAPIError, match="forbidden"):
        await list_server_groups(cast(AutomoxClient, client), org_id=1)


@pytest.mark.asyncio
async def test_get_server_group_api_error_propagates():
    client = StubClient()

    async def _raise(*a: Any, **kw: Any) -> Any:
        raise AutomoxAPIError("not found", status_code=404)

    client.get = _raise  # type: ignore[assignment]
    with pytest.raises(AutomoxAPIError, match="not found"):
        await get_server_group(cast(AutomoxClient, client), org_id=1, group_id=999)

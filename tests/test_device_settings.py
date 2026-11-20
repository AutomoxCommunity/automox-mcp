"""Tests for the device settings workflows and tools.

Response fixtures are sanitized payloads captured from a live organization whose
devices own their settings (ids replaced).
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import FakeClient, StubClient, StubServer
from fastmcp.exceptions import ToolError

from automox_mcp import workflows
from automox_mcp.client import AutomoxAPIError
from automox_mcp.tools import device_settings_tools
from automox_mcp.workflows import groups as group_workflows

ORG_UUID = "ABCDEF01-2345-4678-9abc-def012345678"
BASE = "/organizations/abcdef01-2345-4678-9abc-def012345678/scan/device-settings"
DEVICE_A = "11111111-1111-4111-8111-111111111111"
DEVICE_B = "22222222-2222-4222-8222-222222222222"
JOB_ID = "33333333-3333-4333-8333-333333333333"

JOB_ACCEPTED = {
    "jobId": JOB_ID,
    "setting": "scan-interval",
    "status": "PENDING",
    "add": {"deviceCount": 1, "goneBeforeStart": 0},
    "createdAt": "2026-11-20T16:44:12.833Z",
}

JOB_COMPLETED = {
    "jobId": JOB_ID,
    "setting": "scan-interval",
    "status": "COMPLETED",
    "add": {
        "value": {"intervalMinutes": 1440},
        "deviceCount": 1,
        "goneBeforeStart": 0,
        "outcomes": {
            "applied": 1,
            "superseded": 0,
            "notInOrg": 0,
            "gone": 0,
            "notApplicable": 0,
            "failed": 0,
        },
    },
    "requestedBy": None,
    "createdAt": "2026-11-20T16:44:12.833Z",
    "startedAt": "2026-11-20T16:44:13.857Z",
    "completedAt": "2026-11-20T16:44:14.086Z",
}


def _problem(status: int, title: str, detail: str, code: str) -> dict[str, Any]:
    return {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": f"/api{BASE}",
        "error": detail,
        "code": code,
    }


class RaisingClient(StubClient):
    """StubClient whose POST/GET/PUT raise a given AutomoxAPIError."""

    def __init__(self, exc: AutomoxAPIError) -> None:
        super().__init__()
        self.exc = exc

    async def post(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("POST", path, kwargs.get("json_data")))
        raise self.exc

    async def get(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("GET", path, kwargs.get("params")))
        raise self.exc

    async def put(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("PUT", path, kwargs.get("json_data")))
        raise self.exc


# ---------------------------------------------------------------------------
# build_setting_value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("setting", "kwargs", "expected"),
    [
        ("scan-interval", {"interval_minutes": 720}, {"intervalMinutes": 720}),
        ("os-auto-update", {"os_auto_update": "DISABLED"}, {"state": "DISABLED"}),
        ("windows-update-source", {"windows_update_source": "KEEP"}, {"state": "KEEP"}),
        (
            "windows-update-source",
            {"windows_update_source": "WINDOWS_UPDATE"},
            {"managed": False, "serverUrl": None},
        ),
        (
            "windows-update-source",
            {"windows_update_source": "WSUS", "wsus_server_url": "https://wsus.example.com:8531"},
            {"managed": True, "serverUrl": "https://wsus.example.com:8531"},
        ),
    ],
)
def test_build_setting_value(
    setting: str, kwargs: dict[str, Any], expected: dict[str, Any]
) -> None:
    assert workflows.build_setting_value(setting, **kwargs) == expected


@pytest.mark.parametrize(
    ("setting", "kwargs", "message"),
    [
        ("scan-interval", {}, "interval_minutes is required"),
        ("scan-interval", {"interval_minutes": 720, "os_auto_update": "KEEP"}, "does not apply"),
        ("os-auto-update", {}, "os_auto_update is required"),
        ("windows-update-source", {}, "windows_update_source is required"),
        ("windows-update-source", {"windows_update_source": "WSUS"}, "wsus_server_url is required"),
        (
            "windows-update-source",
            {"windows_update_source": "KEEP", "wsus_server_url": "https://wsus.example.com"},
            "applies only when",
        ),
    ],
)
def test_build_setting_value_rejects(setting: str, kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        workflows.build_setting_value(setting, **kwargs)


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_job_posts_body_to_lowercase_org_path() -> None:
    client = StubClient(post_responses={f"{BASE}/jobs": [JOB_ACCEPTED]})
    result = await workflows.create_device_settings_job(
        client,  # type: ignore[arg-type]
        org_uuid=ORG_UUID,
        setting="scan-interval",
        value={"intervalMinutes": 1440},
        add_device_uuids=[DEVICE_A],
        remove_device_uuids=[DEVICE_B],
    )
    assert client.calls == [
        (
            "POST",
            f"{BASE}/jobs",
            {
                "setting": "scan-interval",
                "value": {"intervalMinutes": 1440},
                "add": {"deviceUuids": [DEVICE_A]},
                "remove": {"deviceUuids": [DEVICE_B]},
            },
        )
    ]
    assert result["data"]["jobId"] == JOB_ID
    assert "get_device_settings_job" in result["metadata"]["next_step"]


@pytest.mark.asyncio
async def test_create_job_omits_empty_remove() -> None:
    client = StubClient(post_responses={f"{BASE}/jobs": [JOB_ACCEPTED]})
    await workflows.create_device_settings_job(
        client,  # type: ignore[arg-type]
        org_uuid=ORG_UUID,
        setting="scan-interval",
        value={"intervalMinutes": 1440},
        add_device_uuids=[DEVICE_A],
    )
    assert "remove" not in client.calls[0][2]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [0, 500, 503])
async def test_create_job_unclear_result_warns_against_blind_resend(status: int) -> None:
    client = RaisingClient(AutomoxAPIError("boom", status_code=status))
    with pytest.raises(AutomoxAPIError, match="list_device_settings_jobs") as info:
        await workflows.create_device_settings_job(
            client,  # type: ignore[arg-type]
            org_uuid=ORG_UUID,
            setting="scan-interval",
            value={"intervalMinutes": 1440},
            add_device_uuids=[DEVICE_A],
        )
    assert info.value.status_code == status
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_create_job_org_not_device_owned_points_to_group_tool() -> None:
    payload = _problem(
        409, "Conflict", "settings are managed on server groups", "ORG_NOT_DEVICE_OWNED"
    )
    client = RaisingClient(AutomoxAPIError("conflict", status_code=409, payload=payload))
    with pytest.raises(AutomoxAPIError) as info:
        await workflows.create_device_settings_job(
            client,  # type: ignore[arg-type]
            org_uuid=ORG_UUID,
            setting="scan-interval",
            value={"intervalMinutes": 1440},
            add_device_uuids=[DEVICE_A],
        )
    message = str(info.value)
    assert "code=ORG_NOT_DEVICE_OWNED" in message
    assert "retry=action" in message
    assert "update_server_group" in message
    assert info.value.payload == payload


@pytest.mark.asyncio
async def test_get_job_returns_job() -> None:
    client = StubClient(get_responses={f"{BASE}/jobs/{JOB_ID}": [JOB_COMPLETED]})
    result = await workflows.get_device_settings_job(
        client,  # type: ignore[arg-type]
        org_uuid=ORG_UUID,
        job_id=JOB_ID,
    )
    assert result["data"] == JOB_COMPLETED


@pytest.mark.asyncio
async def test_get_missing_job_keeps_code() -> None:
    payload = _problem(404, "Not Found", "job not found", "JOB_NOT_FOUND")
    client = RaisingClient(AutomoxAPIError("not found", status_code=404, payload=payload))
    with pytest.raises(AutomoxAPIError, match="code=JOB_NOT_FOUND, retry=no"):
        await workflows.get_device_settings_job(
            client,  # type: ignore[arg-type]
            org_uuid=ORG_UUID,
            job_id="missing",
        )


@pytest.mark.asyncio
async def test_error_without_known_code_is_unchanged() -> None:
    exc = AutomoxAPIError("Forbidden", status_code=403, payload={"message": "Forbidden"})
    client = RaisingClient(exc)
    with pytest.raises(AutomoxAPIError) as info:
        await workflows.get_device_settings_job(
            client,  # type: ignore[arg-type]
            org_uuid=ORG_UUID,
            job_id=JOB_ID,
        )
    assert info.value is exc


@pytest.mark.asyncio
async def test_list_jobs_passes_filters_and_reports_cursor() -> None:
    client = StubClient(
        get_responses={f"{BASE}/jobs": [{"jobs": [JOB_COMPLETED], "lastEvaluatedKey": "next"}]}
    )
    result = await workflows.list_device_settings_jobs(
        client,  # type: ignore[arg-type]
        org_uuid=ORG_UUID,
        setting="scan-interval",
        limit=10,
        cursor="prev",
    )
    assert client.calls == [
        ("GET", f"{BASE}/jobs", {"setting": "scan-interval", "limit": 10, "cursor": "prev"})
    ]
    assert result["data"]["jobs"] == [JOB_COMPLETED]
    assert result["metadata"]["next_cursor"] == "next"
    assert result["metadata"]["complete"] is False


@pytest.mark.asyncio
async def test_list_jobs_last_page_is_complete() -> None:
    client = StubClient(get_responses={f"{BASE}/jobs": [{"jobs": [], "lastEvaluatedKey": None}]})
    result = await workflows.list_device_settings_jobs(
        client,  # type: ignore[arg-type]
        org_uuid=ORG_UUID,
    )
    assert client.calls == [("GET", f"{BASE}/jobs", None)]
    assert result["data"]["jobs"] == []
    assert result["metadata"]["complete"] is True


@pytest.mark.asyncio
async def test_cancel_job_reports_cancelled() -> None:
    cancelled = {**JOB_COMPLETED, "status": "CANCELLED"}
    client = StubClient(post_responses={f"{BASE}/jobs/{JOB_ID}/cancel": [cancelled]})
    result = await workflows.cancel_device_settings_job(
        client,  # type: ignore[arg-type]
        org_uuid=ORG_UUID,
        job_id=JOB_ID,
    )
    assert result["data"]["status"] == "CANCELLED"
    assert result["metadata"]["cancelled"] is True


@pytest.mark.asyncio
async def test_cancel_finished_job_returns_job_not_error() -> None:
    refused = {k: v for k, v in JOB_COMPLETED.items()}
    client = RaisingClient(AutomoxAPIError("conflict", status_code=409, payload=refused))
    result = await workflows.cancel_device_settings_job(
        client,  # type: ignore[arg-type]
        org_uuid=ORG_UUID,
        job_id=JOB_ID,
    )
    assert result["data"]["status"] == "COMPLETED"
    assert result["metadata"]["cancelled"] is False
    assert "COMPLETED" in result["metadata"]["note"]


@pytest.mark.asyncio
async def test_cancel_conflict_with_code_raises() -> None:
    payload = _problem(409, "Conflict", "organization is locked", "ORG_OUT_OF_SCOPE")
    client = RaisingClient(AutomoxAPIError("conflict", status_code=409, payload=payload))
    with pytest.raises(AutomoxAPIError, match="code=ORG_OUT_OF_SCOPE"):
        await workflows.cancel_device_settings_job(
            client,  # type: ignore[arg-type]
            org_uuid=ORG_UUID,
            job_id=JOB_ID,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setting", "kwargs", "body"),
    [
        ("scan-interval", {"interval_minutes": 480}, {"intervalMinutes": 480}),
        (
            "windows-update-source",
            {"wsus_server_url": "https://wsus.example.com"},
            {"managed": True, "serverUrl": "https://wsus.example.com"},
        ),
    ],
)
async def test_add_value_posts_body(setting: str, kwargs: dict[str, Any], body: Any) -> None:
    client = StubClient(
        post_responses={f"{BASE}/values/{setting}": [{"setting": setting, "value": body}]}
    )
    result = await workflows.add_device_setting_value(
        client,  # type: ignore[arg-type]
        org_uuid=ORG_UUID,
        setting=setting,
        **kwargs,
    )
    assert client.calls == [("POST", f"{BASE}/values/{setting}", body)]
    assert result["data"] == {"setting": setting, "value": body}


@pytest.mark.asyncio
async def test_add_existing_value_keeps_code() -> None:
    payload = _problem(409, "Conflict", "this scan interval is already configured", "VALUE_EXISTS")
    client = RaisingClient(AutomoxAPIError("conflict", status_code=409, payload=payload))
    with pytest.raises(AutomoxAPIError, match="code=VALUE_EXISTS"):
        await workflows.add_device_setting_value(
            client,  # type: ignore[arg-type]
            org_uuid=ORG_UUID,
            setting="scan-interval",
            interval_minutes=1440,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setting", "kwargs"),
    [
        ("scan-interval", {}),
        ("scan-interval", {"interval_minutes": 480, "wsus_server_url": "https://w.example.com"}),
        ("windows-update-source", {}),
        (
            "windows-update-source",
            {"wsus_server_url": "https://w.example.com", "interval_minutes": 480},
        ),
    ],
)
async def test_add_value_rejects_wrong_arguments(setting: str, kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        await workflows.add_device_setting_value(
            StubClient(),  # type: ignore[arg-type]
            org_uuid=ORG_UUID,
            setting=setting,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Group tools point device-owned refusals at the new tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_create_device_owned_refusal_points_to_job_tool() -> None:
    payload = {"code": "DEVICE_OWNED_SETTINGS", "errors": ["refresh_interval is device-owned"]}
    client = RaisingClient(AutomoxAPIError("unprocessable", status_code=422, payload=payload))
    with pytest.raises(AutomoxAPIError, match="create_device_settings_job") as info:
        await group_workflows.create_server_group(
            client,  # type: ignore[arg-type]
            org_id=42,
            name="g",
            refresh_interval=720,
            parent_server_group_id=1,
        )
    assert info.value.status_code == 422
    assert info.value.payload == payload


@pytest.mark.asyncio
async def test_group_create_other_error_unchanged() -> None:
    exc = AutomoxAPIError("bad", status_code=400, payload={"errors": ["name required"]})
    client = RaisingClient(exc)
    with pytest.raises(AutomoxAPIError) as info:
        await group_workflows.create_server_group(
            client,  # type: ignore[arg-type]
            org_id=42,
            name="g",
            refresh_interval=720,
            parent_server_group_id=1,
        )
    assert info.value is exc


# ---------------------------------------------------------------------------
# Tools: registration and parameter validation
# ---------------------------------------------------------------------------

_READ_TOOLS = {"list_device_settings_jobs", "get_device_settings_job"}
_WRITE_TOOLS = {
    "create_device_settings_job",
    "cancel_device_settings_job",
    "add_device_setting_value",
}


def _register(read_only: bool = False) -> StubServer:
    server = StubServer()
    device_settings_tools.register(server, read_only=read_only, client=FakeClient())  # type: ignore[arg-type]
    return server


def test_read_only_registers_only_read_tools() -> None:
    assert set(_register(read_only=True).tools) == _READ_TOOLS
    assert set(_register().tools) == _READ_TOOLS | _WRITE_TOOLS


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    def fake(name: str):
        async def _fake(client: Any, **kwargs: Any) -> dict[str, Any]:
            calls[name] = kwargs
            return {"data": {}, "metadata": {}}

        return _fake

    for name in (
        "create_device_settings_job",
        "get_device_settings_job",
        "list_device_settings_jobs",
        "cancel_device_settings_job",
        "add_device_setting_value",
    ):
        monkeypatch.setattr(device_settings_tools.workflows, name, fake(name))
    return calls


@pytest.mark.asyncio
async def test_create_tool_builds_value_and_uses_client_org(recorded: dict[str, Any]) -> None:
    server = _register()
    await server.tools["create_device_settings_job"](
        setting="windows-update-source",
        windows_update_source="WSUS",
        wsus_server_url="https://wsus.example.com",
        add_device_uuids=[DEVICE_A],
        remove_device_uuids=[DEVICE_B],
    )
    assert recorded["create_device_settings_job"] == {
        "org_uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "setting": "windows-update-source",
        "value": {"managed": True, "serverUrl": "https://wsus.example.com"},
        "add_device_uuids": [DEVICE_A],
        "remove_device_uuids": [DEVICE_B],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"add_device_uuids": []}, "1 to 500"),
        (
            {"add_device_uuids": [f"{i:08x}-0000-4000-8000-000000000000" for i in range(501)]},
            "1 to 500",
        ),
        ({"add_device_uuids": [DEVICE_A, DEVICE_A.upper()]}, "more than once"),
        ({"add_device_uuids": ["11111111-1111-1111-1111-111111111111"]}, "RFC 9562"),
        ({"add_device_uuids": [DEVICE_A], "remove_device_uuids": [DEVICE_A]}, "both"),
        ({"add_device_uuids": [DEVICE_A], "remove_device_uuids": []}, "1 to 500"),
        ({"add_device_uuids": [DEVICE_A], "os_auto_update": "KEEP"}, "does not apply"),
        ({"add_device_uuids": ["not-a-uuid"]}, "uuid"),
    ],
)
async def test_create_tool_rejects_bad_input(
    recorded: dict[str, Any], kwargs: dict[str, Any], message: str
) -> None:
    server = _register()
    with pytest.raises(ToolError, match=message):
        await server.tools["create_device_settings_job"](
            setting="scan-interval", interval_minutes=720, **kwargs
        )
    assert "create_device_settings_job" not in recorded


@pytest.mark.asyncio
async def test_list_tool_rejects_limit_over_200(recorded: dict[str, Any]) -> None:
    with pytest.raises(ToolError):
        await _register().tools["list_device_settings_jobs"](limit=201)
    assert "list_device_settings_jobs" not in recorded


@pytest.mark.asyncio
async def test_read_and_cancel_tools_dispatch(recorded: dict[str, Any]) -> None:
    server = _register()
    await server.tools["list_device_settings_jobs"](setting="os-auto-update", limit=5)
    await server.tools["get_device_settings_job"](job_id=JOB_ID)
    await server.tools["cancel_device_settings_job"](job_id=JOB_ID)
    org = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert recorded["list_device_settings_jobs"] == {
        "org_uuid": org,
        "setting": "os-auto-update",
        "limit": 5,
    }
    assert recorded["get_device_settings_job"] == {"org_uuid": org, "job_id": JOB_ID}
    assert recorded["cancel_device_settings_job"] == {"org_uuid": org, "job_id": JOB_ID}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "ok"),
    [
        ({"setting": "scan-interval", "interval_minutes": 480}, True),
        ({"setting": "scan-interval", "interval_minutes": 500}, False),
        ({"setting": "scan-interval", "interval_minutes": 180}, False),
        ({"setting": "scan-interval"}, False),
        ({"setting": "windows-update-source", "wsus_server_url": "https://w.example.com"}, True),
        ({"setting": "windows-update-source", "wsus_server_url": "x" * 101}, False),
        ({"setting": "os-auto-update", "interval_minutes": 480}, False),
    ],
)
async def test_add_value_tool_validation(
    recorded: dict[str, Any], kwargs: dict[str, Any], ok: bool
) -> None:
    server = _register()
    if ok:
        await server.tools["add_device_setting_value"](**kwargs)
        assert "add_device_setting_value" in recorded
    else:
        with pytest.raises(ToolError):
            await server.tools["add_device_setting_value"](**kwargs)
        assert "add_device_setting_value" not in recorded

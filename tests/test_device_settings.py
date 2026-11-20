"""Tests for the device settings workflows and tools.

Response fixtures are sanitized payloads captured from a live organization whose
devices own their settings (ids, names and counts replaced).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from conftest import FakeClient, StubClient, StubServer
from fastmcp.exceptions import ToolError

from automox_mcp import workflows
from automox_mcp.client import AutomoxAPIError
from automox_mcp.tools import device_settings_tools
from automox_mcp.workflows import device_settings as device_settings_workflows
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
        interval_minutes=1440,
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
        interval_minutes=1440,
        add_device_uuids=[DEVICE_A],
    )
    assert "remove" not in client.calls[0][2]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [0, 200, 500, 502, 503, 504])
async def test_create_job_unclear_result_warns_against_blind_resend(status: int) -> None:
    client = RaisingClient(AutomoxAPIError("boom", status_code=status))
    with pytest.raises(
        workflows.UnclearJobCreateError, match="list_devices_by_setting_value"
    ) as info:
        await workflows.create_device_settings_job(
            client,  # type: ignore[arg-type]
            org_uuid=ORG_UUID,
            setting="scan-interval",
            interval_minutes=1440,
            add_device_uuids=[DEVICE_A],
        )
    assert info.value.status_code == status
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_create_job_coded_5xx_keeps_its_guidance() -> None:
    payload = _problem(503, "Service Unavailable", "not ready", "ORG_NOT_OPEN")
    client = RaisingClient(AutomoxAPIError("unavailable", status_code=503, payload=payload))
    with pytest.raises(AutomoxAPIError) as info:
        await workflows.create_device_settings_job(
            client,  # type: ignore[arg-type]
            org_uuid=ORG_UUID,
            setting="scan-interval",
            interval_minutes=1440,
            add_device_uuids=[DEVICE_A],
        )
    assert not isinstance(info.value, workflows.UnclearJobCreateError)
    assert "[code=ORG_NOT_OPEN, retry=yes]" in str(info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", sorted(device_settings_workflows._ERROR_GUIDANCE))
async def test_every_error_code_gets_its_retry_class(code: str) -> None:
    retry, hint = device_settings_workflows._ERROR_GUIDANCE[code]
    client = RaisingClient(AutomoxAPIError("refused", status_code=409, payload={"code": code}))
    with pytest.raises(AutomoxAPIError) as info:
        await workflows.get_device_settings_job(
            client,  # type: ignore[arg-type]
            org_uuid=ORG_UUID,
            job_id=JOB_ID,
        )
    assert f"[code={code}, retry={retry}] {hint}" in str(info.value)


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
            interval_minutes=1440,
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
    assert result["metadata"]["pagination"] == {
        "page_size": 10,
        "has_more": True,
        "next_cursor": "next",
    }


@pytest.mark.asyncio
async def test_list_jobs_last_page_is_complete() -> None:
    client = StubClient(get_responses={f"{BASE}/jobs": [{"jobs": [], "lastEvaluatedKey": None}]})
    result = await workflows.list_device_settings_jobs(
        client,  # type: ignore[arg-type]
        org_uuid=ORG_UUID,
    )
    assert client.calls == [("GET", f"{BASE}/jobs", None)]
    assert result["data"]["jobs"] == []
    assert result["metadata"]["pagination"] == {"has_more": False}


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


class _PutRaisingClient(StubClient):
    def __init__(self, group: dict[str, Any], exc: AutomoxAPIError) -> None:
        super().__init__(get_responses={f"/servergroups/{group['id']}": [group]})
        self.exc = exc

    async def put(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("PUT", path, kwargs.get("json_data")))
        raise self.exc


@pytest.mark.asyncio
async def test_group_update_device_owned_refusal_points_to_job_tool() -> None:
    group = {
        "id": 5,
        "name": "g",
        "refresh_interval": None,
        "parent_server_group_id": 1,
        "ui_color": "#059F1D",
        "notes": "",
        "policies": [],
        "server_count": 0,
    }
    payload = {"code": "DEVICE_OWNED_SETTINGS", "errors": ["refresh_interval is device-owned"]}
    client = _PutRaisingClient(
        group, AutomoxAPIError("unprocessable", status_code=422, payload=payload)
    )
    with pytest.raises(AutomoxAPIError, match="create_device_settings_job") as info:
        await group_workflows.update_server_group(
            client,  # type: ignore[arg-type]
            org_id=42,
            group_id=5,
            name="g",
            refresh_interval=720,
        )
    assert info.value.status_code == 422
    assert client.calls[-1][0] == "PUT"


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
# Per-value reads
# ---------------------------------------------------------------------------

READ_BASE = "/orgs/42/device-settings"
WSUS_URL = "http://wsus.example.test:8530"

SCAN_INTERVAL_VALUES = {
    "defaultIntervalMinutes": 1440,
    "values": [
        {
            "intervalMinutes": 720,
            "deviceCount": 0,
            "dateUpdated": "2026-11-11T23:37:12Z",
            "isDefault": False,
        },
        {
            "intervalMinutes": 1440,
            "deviceCount": 3,
            "dateUpdated": "2026-11-12T18:17:22Z",
            "isDefault": True,
        },
    ],
}

OS_PATCH_VALUES = {
    "defaults": {"osAutoUpdate": {"state": "KEEP"}, "windowsUpdateSource": {"state": "KEEP"}},
    "osAutoUpdate": [
        {"value": {"state": "KEEP"}, "deviceCount": 3, "dateUpdated": None, "isDefault": True},
    ],
    "windowsUpdateSource": [
        {"value": {"state": "KEEP"}, "deviceCount": 2, "dateUpdated": None, "isDefault": True},
    ],
    "wsusServers": [
        {
            "serverUrl": WSUS_URL,
            "valueKey": WSUS_URL,
            "deviceCount": 1,
            "dateUpdated": "2026-11-12T18:19:05Z",
            "isDefault": False,
        },
    ],
}


def _device_page(total: int, page: int, limit: int) -> dict[str, Any]:
    return {
        "data": [
            {
                "id": 1001,
                "uuid": DEVICE_A,
                "name": "host-a",
                "ipAddress": "",
                "isOnline": False,
                "osFamily": "Windows",
                "osName": "10 Enterprise",
                "group": {"id": 7, "name": "", "color": "#059F1D"},
                "tags": [],
                "osAutoUpdate": {"state": "KEEP"},
                "windowsUpdateSource": {"managed": True, "serverUrl": WSUS_URL},
            }
        ],
        "total": total,
        "page": page,
        "limit": limit,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setting", "path", "payload"),
    [
        ("scan-interval", f"{READ_BASE}/scan-interval", SCAN_INTERVAL_VALUES),
        ("os-auto-update", f"{READ_BASE}/os-patch", OS_PATCH_VALUES),
        ("windows-update-source", f"{READ_BASE}/os-patch", OS_PATCH_VALUES),
    ],
)
async def test_get_values_reads_route_for_setting(setting: str, path: str, payload: Any) -> None:
    client = StubClient(get_responses={path: [payload]})
    result = await workflows.get_device_setting_values(client, org_id=42, setting=setting)  # type: ignore[arg-type]
    assert client.calls == [("GET", path, None)]
    assert result["data"] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "path", "params"),
    [
        (
            {"setting": "scan-interval", "interval_minutes": 720},
            f"{READ_BASE}/scan-interval/720/devices",
            {"page": 0, "limit": 50},
        ),
        (
            {"setting": "os-auto-update", "os_auto_update": "ENABLED"},
            f"{READ_BASE}/os-patch/os-auto-update/enabled/devices",
            {"page": 0, "limit": 50},
        ),
        (
            {"setting": "windows-update-source", "windows_update_source": "WINDOWS_UPDATE"},
            f"{READ_BASE}/os-patch/windows-update-source/windows-update/devices",
            {"page": 0, "limit": 50},
        ),
        (
            {
                "setting": "windows-update-source",
                "windows_update_source": "WSUS",
                "wsus_server_url": WSUS_URL,
            },
            f"{READ_BASE}/os-patch/windows-update-source/wsus/devices",
            {"page": 0, "limit": 50, "server": WSUS_URL},
        ),
    ],
)
async def test_list_devices_builds_path_for_value(
    kwargs: dict[str, Any], path: str, params: dict[str, Any]
) -> None:
    client = StubClient(get_responses={path: [_device_page(1, 0, 100)]})
    result = await workflows.list_devices_by_setting_value(client, org_id=42, **kwargs)  # type: ignore[arg-type]
    assert client.calls == [("GET", path, params)]
    assert result["data"]["devices"][0]["uuid"] == DEVICE_A


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("total", "page", "limit", "has_more"),
    [(5, 0, 2, True), (5, 2, 2, False), (4, 1, 2, False), (0, 0, 50, False)],
)
async def test_list_devices_reports_completion(
    total: int, page: int, limit: int, has_more: bool
) -> None:
    path = f"{READ_BASE}/scan-interval/1440/devices"
    client = StubClient(get_responses={path: [_device_page(total, page, limit)]})
    result = await workflows.list_devices_by_setting_value(
        client,  # type: ignore[arg-type]
        org_id=42,
        setting="scan-interval",
        interval_minutes=1440,
        page=page,
        limit=limit,
    )
    pagination = result["metadata"]["pagination"]
    assert pagination["total_elements"] == total
    assert (pagination["page"], pagination["page_size"]) == (page, limit)
    assert pagination["has_more"] is has_more


@pytest.mark.asyncio
async def test_list_devices_returns_only_targeting_fields() -> None:
    path = f"{READ_BASE}/scan-interval/1440/devices"
    client = StubClient(get_responses={path: [_device_page(1, 0, 50)]})
    result = await workflows.list_devices_by_setting_value(
        client,  # type: ignore[arg-type]
        org_id=42,
        setting="scan-interval",
        interval_minutes=1440,
    )
    assert result["data"]["devices"] == [
        {
            "uuid": DEVICE_A,
            "name": "host-a",
            "isOnline": False,
            "osFamily": "Windows",
            "osName": "10 Enterprise",
        }
    ]
    assert client.calls[0][2] == {"page": 0, "limit": 50}


@pytest.mark.asyncio
@pytest.mark.parametrize(("limit", "has_more"), [(1, True), (2, False)])
async def test_list_devices_without_total_uses_page_fill(limit: int, has_more: bool) -> None:
    path = f"{READ_BASE}/scan-interval/1440/devices"
    page = _device_page(1, 0, limit)
    del page["total"]
    client = StubClient(get_responses={path: [page]})
    result = await workflows.list_devices_by_setting_value(
        client,  # type: ignore[arg-type]
        org_id=42,
        setting="scan-interval",
        interval_minutes=1440,
        limit=limit,
    )
    assert "total_elements" not in result["metadata"]["pagination"]
    assert result["metadata"]["pagination"]["has_more"] is has_more


@pytest.mark.asyncio
async def test_list_devices_unknown_value_keeps_code() -> None:
    exc = AutomoxAPIError(
        "automox API error",
        404,
        {
            "errors": ["This scan interval is not configured for the organization."],
            "code": "VALUE_NOT_FOUND",
        },
    )
    with pytest.raises(AutomoxAPIError) as info:
        await workflows.list_devices_by_setting_value(
            RaisingClient(exc),  # type: ignore[arg-type]
            org_id=42,
            setting="scan-interval",
            interval_minutes=9999,
        )
    assert "[code=VALUE_NOT_FOUND, retry=no]" in str(info.value)
    assert "get_device_setting_values" in str(info.value)


@pytest.mark.asyncio
async def test_get_values_group_owned_org_points_to_group_tool() -> None:
    exc = AutomoxAPIError(
        "automox API error",
        409,
        {
            "errors": ["This organization's devices do not own their settings."],
            "code": "ORG_NOT_DEVICE_OWNED",
        },
    )
    with pytest.raises(AutomoxAPIError, match="update_server_group"):
        await workflows.get_device_setting_values(
            RaisingClient(exc),  # type: ignore[arg-type]
            org_id=42,
            setting="scan-interval",
        )


# ---------------------------------------------------------------------------
# Tools: registration and parameter validation
# ---------------------------------------------------------------------------

_READ_TOOLS = {
    "list_device_settings_jobs",
    "get_device_settings_job",
    "get_device_setting_values",
    "list_devices_by_setting_value",
}
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
        "get_device_setting_values",
        "list_devices_by_setting_value",
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
        "windows_update_source": "WSUS",
        "wsus_server_url": "https://wsus.example.com",
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
async def test_list_tool_rejects_limit_over_15(recorded: dict[str, Any]) -> None:
    with pytest.raises(ToolError):
        await _register().tools["list_device_settings_jobs"](limit=16)
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


@pytest.mark.asyncio
async def test_value_read_tools_use_client_org_id(recorded: dict[str, Any]) -> None:
    server = _register()
    await server.tools["get_device_setting_values"](setting="os-auto-update")
    await server.tools["list_devices_by_setting_value"](
        setting="windows-update-source",
        windows_update_source="WSUS",
        wsus_server_url=WSUS_URL,
        page=2,
        limit=50,
    )
    assert recorded["get_device_setting_values"] == {"org_id": 42, "setting": "os-auto-update"}
    assert recorded["list_devices_by_setting_value"] == {
        "org_id": 42,
        "setting": "windows-update-source",
        "windows_update_source": "WSUS",
        "wsus_server_url": WSUS_URL,
        "page": 2,
        "limit": 50,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"setting": "scan-interval", "interval_minutes": 1440, "limit": 51},
        {"setting": "scan-interval", "interval_minutes": 1440, "page": -1},
        {"setting": "scan-interval"},
        {"setting": "windows-update-source", "windows_update_source": "WSUS"},
        {"setting": "os-auto-update", "os_auto_update": "KEEP", "interval_minutes": 60},
    ],
)
async def test_list_devices_tool_rejects_bad_input(
    recorded: dict[str, Any], kwargs: dict[str, Any]
) -> None:
    with pytest.raises(ToolError):
        await _register().tools["list_devices_by_setting_value"](**kwargs)
    assert "list_devices_by_setting_value" not in recorded


@pytest.mark.asyncio
async def test_value_read_tools_accept_explicit_org_id(recorded: dict[str, Any]) -> None:
    server = _register()
    await server.tools["get_device_setting_values"](setting="scan-interval", org_id=7)
    await server.tools["list_devices_by_setting_value"](
        setting="scan-interval", interval_minutes=1440, org_id=7
    )
    assert recorded["get_device_setting_values"]["org_id"] == 7
    assert recorded["list_devices_by_setting_value"]["org_id"] == 7


@pytest.mark.asyncio
async def test_create_tool_treats_empty_remove_as_absent(recorded: dict[str, Any]) -> None:
    await _register().tools["create_device_settings_job"](
        setting="scan-interval",
        interval_minutes=720,
        add_device_uuids=[DEVICE_A],
        remove_device_uuids=[],
    )
    assert "remove_device_uuids" not in recorded["create_device_settings_job"]


def _register_with(client: Any) -> StubServer:
    server = StubServer()
    device_settings_tools.register(server, client=client)
    return server


_CREATE_ARGS: dict[str, Any] = {
    "org_uuid": ORG_UUID,
    "setting": "scan-interval",
    "interval_minutes": 720,
    "add_device_uuids": [DEVICE_A],
}


@pytest.mark.asyncio
async def test_unclear_create_answers_resend_without_sending() -> None:
    client = RaisingClient(AutomoxAPIError("network error", status_code=0))
    tool = _register_with(client).tools["create_device_settings_job"]
    with pytest.raises(ToolError, match="no clear result"):
        await tool(**_CREATE_ARGS, request_id="unclear-create-1")
    again = await tool(**_CREATE_ARGS, request_id="unclear-create-1")
    assert len(client.calls) == 1
    assert again["data"] == {"jobId": None, "unclear": True}
    assert "list_devices_by_setting_value" in again["metadata"]["note"]


@pytest.mark.asyncio
async def test_cancelled_create_answers_resend_without_sending() -> None:
    class CancellingClient(StubClient):
        async def post(self, path: str, **kwargs: Any) -> Any:
            self.calls.append(("POST", path, kwargs.get("json_data")))
            raise asyncio.CancelledError

    client = CancellingClient()
    tool = _register_with(client).tools["create_device_settings_job"]
    with pytest.raises(asyncio.CancelledError):
        await tool(**_CREATE_ARGS, request_id="cancelled-create-1")
    again = await tool(**_CREATE_ARGS, request_id="cancelled-create-1")
    assert len(client.calls) == 1
    assert again["data"]["unclear"] is True


@pytest.mark.asyncio
async def test_refused_create_frees_request_id() -> None:
    payload = _problem(400, "Bad Request", "bad value", "INVALID_VALUE")
    client = RaisingClient(AutomoxAPIError("bad", status_code=400, payload=payload))
    tool = _register_with(client).tools["create_device_settings_job"]
    for _ in range(2):
        with pytest.raises(ToolError, match="INVALID_VALUE"):
            await tool(**_CREATE_ARGS, request_id="refused-create-1")
    assert len(client.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [{}, {"status": "PENDING"}])
async def test_create_without_job_id_is_unclear(answer: dict[str, Any]) -> None:
    client = StubClient(post_responses={f"{BASE}/jobs": [answer]})
    with pytest.raises(workflows.UnclearJobCreateError, match="without a jobId"):
        await workflows.create_device_settings_job(
            client,  # type: ignore[arg-type]
            org_uuid=ORG_UUID,
            setting="scan-interval",
            interval_minutes=720,
            add_device_uuids=[DEVICE_A],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("job_id", [".", "..", "..."])
async def test_job_tools_reject_dot_ids(recorded: dict[str, Any], job_id: str) -> None:
    server = _register()
    for name in ("get_device_settings_job", "cancel_device_settings_job"):
        with pytest.raises(ToolError):
            await server.tools[name](job_id=job_id)
    assert "get_device_settings_job" not in recorded


@pytest.mark.asyncio
async def test_list_jobs_tool_sends_default_limit(recorded: dict[str, Any]) -> None:
    await _register().tools["list_device_settings_jobs"]()
    assert recorded["list_device_settings_jobs"]["limit"] == 10

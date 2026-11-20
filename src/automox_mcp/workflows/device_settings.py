"""Device settings workflows (scan interval, OS auto update, Windows update source).

These settings live on each device in an organization whose devices own their
settings, where server-group saves cannot change them. Changes go through
asynchronous apply jobs under ``/organizations/{orgUuid}/scan/device-settings``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from ..client import AutomoxAPIError, AutomoxClient

_BASE = "/organizations/{org_uuid}/scan/device-settings"
_READ_BASE = "/orgs/{org_id}/device-settings"

# Value -> path slug of the per-value device list under os-patch.
_OS_PATCH_SLUGS: dict[str, dict[str, str]] = {
    "os-auto-update": {"KEEP": "keep", "DISABLED": "disabled", "ENABLED": "enabled"},
    "windows-update-source": {"KEEP": "keep", "WINDOWS_UPDATE": "windows-update", "WSUS": "wsus"},
}

# Error code -> (retry class, what the caller should do). Codes and retry classes
# follow the API's ErrorCode table.
_ERROR_GUIDANCE: dict[str, tuple[str, str]] = {
    "INVALID_SELECTION": ("no", "Fix the device lists: 1 to 500 distinct device UUIDs per half."),
    "SELECTION_OVERLAP": ("no", "A device is in both add and remove; list it in one only."),
    "INVALID_VALUE": ("no", "The value does not fit the setting; check the value arguments."),
    "INVALID_QUERY": ("no", "Fix the setting, limit or cursor argument."),
    "JOB_NOT_FOUND": ("no", "No job with this id in the organization."),
    "SETTING_HAS_NO_VALUES": ("no", "os-auto-update has a fixed set of values; nothing to add."),
    "VALUE_EXISTS": ("no", "The organization already has this value; it can be used in a job."),
    "ORG_NOT_DEVICE_OWNED": (
        "action",
        "This organization's settings are managed on server groups: use "
        "update_server_group (refresh_interval, OS auto update, WSUS) instead.",
    ),
    "ORG_OUT_OF_SCOPE": (
        "action",
        "The organization is deleted or locked. Ask an Automox administrator or "
        "support which; send again once a locked organization is unlocked.",
    ),
    "VALUE_NOT_FOUND": (
        "no",
        "The value, or the WSUS server, is not one of the organization's values; "
        "read them with get_device_setting_values.",
    ),
    "ORG_NOT_OPEN": (
        "yes",
        "The organization is not ready for changes yet; retry later, and contact "
        "Automox support if it persists.",
    ),
}

_UNCLEAR_CREATE = (
    "The job create returned no clear result, so a job may already have been "
    "created. Do not resend it blindly: call list_device_settings_jobs to look for "
    "it first. Resending is safe only if no later job for the same setting has "
    "been sent since; otherwise leave the devices that job shares out of the retry."
)


def _base(org_uuid: str) -> str:
    # The platform refuses an orgUuid that is not lowercase.
    return _BASE.format(org_uuid=quote(org_uuid.lower(), safe=""))


def _with_guidance(exc: AutomoxAPIError) -> AutomoxAPIError:
    code = exc.payload.get("code") if isinstance(exc.payload, Mapping) else None
    guidance = _ERROR_GUIDANCE.get(code) if isinstance(code, str) else None
    if guidance is None:
        return exc
    retry, hint = guidance
    return AutomoxAPIError(
        f"{exc} [code={code}, retry={retry}] {hint}", exc.status_code, exc.payload
    )


def _is_unclear(exc: AutomoxAPIError) -> bool:
    # status 0 = no response (network error); 500/503 may have created the job.
    return exc.status_code in (0, 500, 503)


def build_setting_value(
    setting: str,
    *,
    interval_minutes: int | None = None,
    os_auto_update: str | None = None,
    windows_update_source: str | None = None,
    wsus_server_url: str | None = None,
) -> dict[str, Any]:
    """Build the job ``value`` for *setting* from the flat tool arguments."""
    given = {
        "interval_minutes": interval_minutes,
        "os_auto_update": os_auto_update,
        "windows_update_source": windows_update_source,
        "wsus_server_url": wsus_server_url,
    }
    allowed = {
        "scan-interval": {"interval_minutes"},
        "os-auto-update": {"os_auto_update"},
        "windows-update-source": {"windows_update_source", "wsus_server_url"},
    }[setting]
    extra = sorted(
        name for name, value in given.items() if value is not None and name not in allowed
    )
    if extra:
        raise ValueError(f"{', '.join(extra)} does not apply to setting {setting}")

    if setting == "scan-interval":
        if interval_minutes is None:
            raise ValueError("interval_minutes is required for scan-interval")
        return {"intervalMinutes": interval_minutes}
    if setting == "os-auto-update":
        if os_auto_update is None:
            raise ValueError("os_auto_update is required for os-auto-update")
        return {"state": os_auto_update}

    if windows_update_source is None:
        raise ValueError("windows_update_source is required for windows-update-source")
    if windows_update_source == "WSUS":
        if not wsus_server_url:
            raise ValueError("wsus_server_url is required when windows_update_source is WSUS")
        return {"managed": True, "serverUrl": wsus_server_url}
    if wsus_server_url is not None:
        raise ValueError("wsus_server_url applies only when windows_update_source is WSUS")
    if windows_update_source == "WINDOWS_UPDATE":
        return {"managed": False, "serverUrl": None}
    return {"state": "KEEP"}


async def create_device_settings_job(
    client: AutomoxClient,
    *,
    org_uuid: str,
    setting: str,
    value: Mapping[str, Any],
    add_device_uuids: list[str],
    remove_device_uuids: list[str] | None = None,
) -> dict[str, Any]:
    """Create an apply job that sets one setting on the devices in ``add``."""
    body: dict[str, Any] = {
        "setting": setting,
        "value": dict(value),
        "add": {"deviceUuids": add_device_uuids},
    }
    if remove_device_uuids:
        body["remove"] = {"deviceUuids": remove_device_uuids}
    try:
        result = await client.post(f"{_base(org_uuid)}/jobs", json_data=body)
    except AutomoxAPIError as exc:
        if _is_unclear(exc):
            raise AutomoxAPIError(
                f"{exc}. {_UNCLEAR_CREATE}", exc.status_code, exc.payload
            ) from exc
        raise _with_guidance(exc) from exc
    return {
        "data": result,
        "metadata": {
            "next_step": (
                "The job runs in the background. Poll get_device_settings_job with "
                "this jobId until status is COMPLETED, PARTIAL, FAILED or CANCELLED."
            ),
        },
    }


async def get_device_settings_job(
    client: AutomoxClient, *, org_uuid: str, job_id: str
) -> dict[str, Any]:
    """Read one apply job with its per-half outcome counts."""
    try:
        result = await client.get(f"{_base(org_uuid)}/jobs/{quote(job_id, safe='')}")
    except AutomoxAPIError as exc:
        raise _with_guidance(exc) from exc
    return {"data": result, "metadata": {}}


async def list_device_settings_jobs(
    client: AutomoxClient,
    *,
    org_uuid: str,
    setting: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List the organization's apply jobs that are still in progress."""
    params: dict[str, Any] = {}
    if setting is not None:
        params["setting"] = setting
    if limit is not None:
        params["limit"] = limit
    if cursor is not None:
        params["cursor"] = cursor
    try:
        result = await client.get(f"{_base(org_uuid)}/jobs", params=params or None)
    except AutomoxAPIError as exc:
        raise _with_guidance(exc) from exc
    jobs = result.get("jobs", []) if isinstance(result, Mapping) else []
    next_cursor = result.get("lastEvaluatedKey") if isinstance(result, Mapping) else None
    return {
        "data": {"jobs": jobs},
        "metadata": {
            "next_cursor": next_cursor,
            "complete": next_cursor is None,
            "note": (
                "Only jobs in progress are listed; read a finished job by its jobId. "
                "A page can be empty and still have a next_cursor."
            ),
        },
    }


async def cancel_device_settings_job(
    client: AutomoxClient, *, org_uuid: str, job_id: str
) -> dict[str, Any]:
    """Cancel an apply job; devices it already changed keep the new value."""
    try:
        result = await client.post(f"{_base(org_uuid)}/jobs/{quote(job_id, safe='')}/cancel")
    except AutomoxAPIError as exc:
        payload = exc.payload if isinstance(exc.payload, Mapping) else {}
        # A refused cancel is a 409 whose body is the job itself, with no code.
        if exc.status_code == 409 and "code" not in payload and "jobId" in payload:
            return {
                "data": dict(payload),
                "metadata": {
                    "cancelled": False,
                    "note": f"The job was not cancelled; it is already {payload.get('status')}.",
                },
            }
        raise _with_guidance(exc) from exc
    return {
        "data": result,
        "metadata": {
            "cancelled": True,
            "note": (
                "Devices already changed keep the new value, and devices already started "
                "may still change; counts are final once the job leaves "
                "list_device_settings_jobs."
            ),
        },
    }


async def add_device_setting_value(
    client: AutomoxClient,
    *,
    org_uuid: str,
    setting: str,
    interval_minutes: int | None = None,
    wsus_server_url: str | None = None,
) -> dict[str, Any]:
    """Add a scan interval or WSUS server to the organization's list of values."""
    if setting == "scan-interval":
        if interval_minutes is None or wsus_server_url is not None:
            raise ValueError("scan-interval takes interval_minutes only")
        body: dict[str, Any] = {"intervalMinutes": interval_minutes}
    else:
        if not wsus_server_url or interval_minutes is not None:
            raise ValueError("windows-update-source takes wsus_server_url only")
        body = {"managed": True, "serverUrl": wsus_server_url}
    try:
        result = await client.post(
            f"{_base(org_uuid)}/values/{quote(setting, safe='')}", json_data=body
        )
    except AutomoxAPIError as exc:
        raise _with_guidance(exc) from exc
    return {"data": result, "metadata": {}}


async def get_device_setting_values(
    client: AutomoxClient, *, org_id: int, setting: str
) -> dict[str, Any]:
    """Read the organization's values for *setting*, each with its device count."""
    group = "scan-interval" if setting == "scan-interval" else "os-patch"
    try:
        result = await client.get(f"{_READ_BASE.format(org_id=org_id)}/{group}")
    except AutomoxAPIError as exc:
        raise _with_guidance(exc) from exc
    return {"data": result, "metadata": {}}


async def list_devices_by_setting_value(
    client: AutomoxClient,
    *,
    org_id: int,
    setting: str,
    interval_minutes: int | None = None,
    os_auto_update: str | None = None,
    windows_update_source: str | None = None,
    wsus_server_url: str | None = None,
    page: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """List one page of the devices that hold one value of *setting*."""
    value = build_setting_value(
        setting,
        interval_minutes=interval_minutes,
        os_auto_update=os_auto_update,
        windows_update_source=windows_update_source,
        wsus_server_url=wsus_server_url,
    )
    base = _READ_BASE.format(org_id=org_id)
    params: dict[str, Any] = {"page": page, "limit": limit}
    if setting == "scan-interval":
        path = f"{base}/scan-interval/{value['intervalMinutes']}/devices"
    else:
        chosen = os_auto_update if setting == "os-auto-update" else windows_update_source
        path = f"{base}/os-patch/{setting}/{_OS_PATCH_SLUGS[setting][str(chosen)]}/devices"
        if wsus_server_url is not None:
            params["server"] = wsus_server_url
    try:
        result = await client.get(path, params=params)
    except AutomoxAPIError as exc:
        raise _with_guidance(exc) from exc
    devices = result.get("data", []) if isinstance(result, Mapping) else []
    total = result.get("total") if isinstance(result, Mapping) else None
    complete = not isinstance(total, int) or (page + 1) * limit >= total
    return {
        "data": {"devices": devices},
        "metadata": {"total": total, "page": page, "limit": limit, "complete": complete},
    }


__all__ = [
    "add_device_setting_value",
    "build_setting_value",
    "cancel_device_settings_job",
    "create_device_settings_job",
    "get_device_setting_values",
    "get_device_settings_job",
    "list_device_settings_jobs",
    "list_devices_by_setting_value",
]

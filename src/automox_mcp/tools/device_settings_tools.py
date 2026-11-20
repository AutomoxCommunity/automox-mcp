"""Device settings tools: change scan interval, OS auto update and Windows update source
per device in organizations whose devices own their settings."""

from __future__ import annotations

import uuid as uuid_lib
from typing import Any, Literal
from uuid import UUID

from fastmcp import FastMCP
from pydantic import Field, field_validator, model_validator

from .. import workflows
from ..client import AutomoxClient
from ..schemas import ForbidExtraModel, OrgIdRequiredMixin
from ..utils.tooling import (
    call_tool_workflow,
    check_idempotency,
    release_idempotency,
    store_idempotency,
)

SettingName = Literal["scan-interval", "os-auto-update", "windows-update-source"]
OsAutoUpdate = Literal["ENABLED", "DISABLED", "KEEP"]
WindowsUpdateSource = Literal["KEEP", "WINDOWS_UPDATE", "WSUS"]

_MAX_DEVICES = 500
_MAX_PAGE_LIMIT = 500
# RFC 9562 defines UUID versions 1 to 8.
_UUID_VERSIONS = range(1, 9)

_OWNERSHIP_NOTE = (
    "Only for organizations whose devices own their settings (server groups there "
    "read refresh_interval as null); otherwise the API answers ORG_NOT_DEVICE_OWNED "
    "and the settings are changed with update_server_group."
)


def _check_device_uuids(values: list[UUID] | None, field: str) -> list[UUID] | None:
    if not values:
        if values is not None and field == "add_device_uuids":
            raise ValueError(f"{field} must list 1 to {_MAX_DEVICES} devices")
        return None
    if len(values) > _MAX_DEVICES:
        raise ValueError(
            f"{field} must list 1 to {_MAX_DEVICES} devices; split a larger set into "
            "jobs yourself, knowing that the newest job for a setting wins on every "
            "device it shares with an earlier one"
        )
    if len(set(values)) != len(values):
        raise ValueError(f"{field} lists a device more than once")
    for value in values:
        if value.variant != uuid_lib.RFC_4122 or value.version not in _UUID_VERSIONS:
            raise ValueError(f"{field} holds {value}, which is not an RFC 9562 UUID")
    return values


class _SettingValueFields(ForbidExtraModel):
    """One value of one setting, given as flat arguments."""

    setting: SettingName
    interval_minutes: int | None = Field(None, ge=1)
    os_auto_update: OsAutoUpdate | None = None
    windows_update_source: WindowsUpdateSource | None = None
    wsus_server_url: str | None = Field(None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def _check_setting_value(self) -> _SettingValueFields:
        workflows.build_setting_value(
            self.setting,
            interval_minutes=self.interval_minutes,
            os_auto_update=self.os_auto_update,
            windows_update_source=self.windows_update_source,
            wsus_server_url=self.wsus_server_url,
        )
        return self


class CreateDeviceSettingsJobParams(_SettingValueFields):
    org_uuid: UUID
    add_device_uuids: list[UUID]
    remove_device_uuids: list[UUID] | None = None

    @field_validator("add_device_uuids")
    @classmethod
    def _check_add(cls, value: list[UUID]) -> list[UUID] | None:
        return _check_device_uuids(value, "add_device_uuids")

    @field_validator("remove_device_uuids")
    @classmethod
    def _check_remove(cls, value: list[UUID] | None) -> list[UUID] | None:
        return _check_device_uuids(value, "remove_device_uuids")

    @model_validator(mode="after")
    def _check_halves(self) -> CreateDeviceSettingsJobParams:
        if self.remove_device_uuids and set(self.add_device_uuids) & set(self.remove_device_uuids):
            raise ValueError("a device is in both add_device_uuids and remove_device_uuids")
        return self


class DeviceSettingsJobParams(ForbidExtraModel):
    org_uuid: UUID
    job_id: str = Field(min_length=1, max_length=200)


class ListDeviceSettingsJobsParams(ForbidExtraModel):
    org_uuid: UUID
    setting: SettingName | None = None
    limit: int | None = Field(None, ge=1, le=200)
    cursor: str | None = Field(None, min_length=1, max_length=2000)


class AddDeviceSettingValueParams(ForbidExtraModel):
    org_uuid: UUID
    setting: Literal["scan-interval", "windows-update-source"]
    interval_minutes: int | None = Field(None, ge=240, le=1440, multiple_of=60)
    wsus_server_url: str | None = Field(None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def _check_value(self) -> AddDeviceSettingValueParams:
        if self.setting == "scan-interval":
            if self.interval_minutes is None or self.wsus_server_url is not None:
                raise ValueError("scan-interval takes interval_minutes only")
        elif not self.wsus_server_url or self.interval_minutes is not None:
            raise ValueError("windows-update-source takes wsus_server_url only")
        return self


class GetDeviceSettingValuesParams(OrgIdRequiredMixin, ForbidExtraModel):
    setting: SettingName


class ListDevicesBySettingValueParams(OrgIdRequiredMixin, _SettingValueFields):
    page: int = Field(0, ge=0)
    limit: int = Field(50, ge=1, le=_MAX_PAGE_LIMIT)


def _with_org_id(params: dict[str, Any], org_id: int | None) -> dict[str, Any]:
    # An absent org_id falls back to the client's organization.
    return params if org_id is None else {**params, "org_id": org_id}


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register device settings tools."""

    @server.tool(
        name="list_device_settings_jobs",
        description=(
            "List the organization's device settings apply jobs that are still in "
            "progress (PENDING, RUNNING, or CANCELLED and still finishing), newest "
            "first, including jobs created in the Automox console. A finished job is "
            "not listed: read it with get_device_settings_job. Page with cursor until "
            "metadata.complete is true. " + _OWNERSHIP_NOTE
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def list_device_settings_jobs(
        setting: SettingName | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        org_uuid: str | None = None,
    ) -> dict[str, Any]:
        params = {"org_uuid": org_uuid, "setting": setting, "limit": limit, "cursor": cursor}
        return await call_tool_workflow(
            client,
            workflows.list_device_settings_jobs,
            params,
            params_model=ListDeviceSettingsJobsParams,
            org_uuid_field="org_uuid",
            dump_mode="json",
        )

    @server.tool(
        name="get_device_settings_job",
        description=(
            "Read one device settings apply job: status (PENDING, RUNNING, COMPLETED, "
            "PARTIAL, FAILED, CANCELLED) and, per half (add, remove), the value, the "
            "device count and outcome counts (applied, superseded, notInOrg, gone, "
            "notApplicable, failed). COMPLETED means no device failed, not that every "
            "device changed. The job reports counts, not which devices."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_device_settings_job(
        job_id: str,
        org_uuid: str | None = None,
    ) -> dict[str, Any]:
        return await call_tool_workflow(
            client,
            workflows.get_device_settings_job,
            {"org_uuid": org_uuid, "job_id": job_id},
            params_model=DeviceSettingsJobParams,
            org_uuid_field="org_uuid",
            dump_mode="json",
        )

    @server.tool(
        name="get_device_setting_values",
        description=(
            "Read the values an organization has for a device setting, each with how "
            "many devices hold it, and which value is the default. setting=scan-interval "
            "returns intervals in minutes; os-auto-update or windows-update-source "
            "returns both OS patch settings and the WSUS servers. Use a value from here "
            "in list_devices_by_setting_value or create_device_settings_job. org_id "
            "defaults to the configured organization. " + _OWNERSHIP_NOTE
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_device_setting_values(
        setting: SettingName,
        org_id: int | None = None,
    ) -> dict[str, Any]:
        return await call_tool_workflow(
            client,
            workflows.get_device_setting_values,
            _with_org_id({"setting": setting}, org_id),
            params_model=GetDeviceSettingValuesParams,
        )

    @server.tool(
        name="list_devices_by_setting_value",
        description=(
            "List the devices that hold one value of a device setting, one page at a "
            "time (page from 0, limit up to 500, default 50), each with its uuid for "
            "create_device_settings_job. Give the value the same way as "
            "create_device_settings_job: interval_minutes, os_auto_update, or "
            "windows_update_source (with wsus_server_url for WSUS). Page until "
            "metadata.complete is true, and read every page before sending a job: a job "
            "moves devices off this list and shifts later pages. If metadata.truncated "
            "is true the page was cut to fit the response size; read it again with a "
            "smaller limit. A value or WSUS server that is not one of the organization's "
            "values returns VALUE_NOT_FOUND. org_id defaults to the configured "
            "organization. " + _OWNERSHIP_NOTE
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def list_devices_by_setting_value(
        setting: SettingName,
        interval_minutes: int | None = None,
        os_auto_update: OsAutoUpdate | None = None,
        windows_update_source: WindowsUpdateSource | None = None,
        wsus_server_url: str | None = None,
        page: int = 0,
        limit: int = 50,
        org_id: int | None = None,
    ) -> dict[str, Any]:
        params = {
            "setting": setting,
            "interval_minutes": interval_minutes,
            "os_auto_update": os_auto_update,
            "windows_update_source": windows_update_source,
            "wsus_server_url": wsus_server_url,
            "page": page,
            "limit": limit,
        }
        return await call_tool_workflow(
            client,
            workflows.list_devices_by_setting_value,
            _with_org_id(params, org_id),
            params_model=ListDevicesBySettingValueParams,
        )

    if read_only:
        return

    @server.tool(
        name="create_device_settings_job",
        description=(
            "Change one device setting on up to 500 devices, as a background job. "
            "setting=scan-interval takes interval_minutes (whole hours, 240 to 1440, "
            "for new values); os-auto-update takes os_auto_update ENABLED, DISABLED "
            "or KEEP (leave the device's own setting); windows-update-source takes "
            "windows_update_source KEEP, WINDOWS_UPDATE or WSUS (with "
            "wsus_server_url, at most 100 characters; a new server is added to the "
            "organization's values). add_device_uuids get the value; devices in the "
            "optional remove_device_uuids that have this value go back to the "
            "organization's default. The newest job for a setting wins on every "
            "device it shares with an earlier job. Returns a jobId: poll "
            "get_device_settings_job. If the call fails with no clear result, a job "
            "may exist: check list_device_settings_jobs before sending it again. " + _OWNERSHIP_NOTE
        ),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def create_device_settings_job(
        setting: SettingName,
        add_device_uuids: list[str],
        interval_minutes: int | None = None,
        os_auto_update: OsAutoUpdate | None = None,
        windows_update_source: WindowsUpdateSource | None = None,
        wsus_server_url: str | None = None,
        remove_device_uuids: list[str] | None = None,
        org_uuid: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        cached = await check_idempotency(request_id, "create_device_settings_job")
        if cached is not None:
            return cached
        params = {
            "org_uuid": org_uuid,
            "setting": setting,
            "interval_minutes": interval_minutes,
            "os_auto_update": os_auto_update,
            "windows_update_source": windows_update_source,
            "wsus_server_url": wsus_server_url,
            "add_device_uuids": add_device_uuids,
            "remove_device_uuids": remove_device_uuids,
        }
        try:
            result = await call_tool_workflow(
                client,
                workflows.create_device_settings_job,
                params,
                params_model=CreateDeviceSettingsJobParams,
                org_uuid_field="org_uuid",
                dump_mode="json",
            )
        except BaseException as exc:
            # A job may exist after an unclear create: keep the request_id taken so
            # a resend with it cannot create a second job.
            if not isinstance(exc.__cause__, workflows.UnclearJobCreateError):
                await release_idempotency(request_id, "create_device_settings_job")
            raise
        await store_idempotency(request_id, "create_device_settings_job", result)
        return result

    @server.tool(
        name="cancel_device_settings_job",
        description=(
            "Cancel a device settings apply job. Devices it has not reached are not "
            "changed; devices it already changed keep the new value (a cancel does "
            "not undo them), and devices it had started may still change. A job that "
            "already finished is returned unchanged with metadata.cancelled false."
        ),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def cancel_device_settings_job(
        job_id: str,
        org_uuid: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        cached = await check_idempotency(request_id, "cancel_device_settings_job")
        if cached is not None:
            return cached
        try:
            result = await call_tool_workflow(
                client,
                workflows.cancel_device_settings_job,
                {"org_uuid": org_uuid, "job_id": job_id},
                params_model=DeviceSettingsJobParams,
                org_uuid_field="org_uuid",
                dump_mode="json",
            )
        except BaseException:
            await release_idempotency(request_id, "cancel_device_settings_job")
            raise
        await store_idempotency(request_id, "cancel_device_settings_job", result)
        return result

    @server.tool(
        name="add_device_setting_value",
        description=(
            "Add a scan interval (interval_minutes: 240 to 1440, a multiple of 60) or "
            "a WSUS server (setting=windows-update-source, wsus_server_url) to the "
            "organization's list of values, without applying it to any device. Not "
            "needed before create_device_settings_job, which adds a new WSUS server "
            "itself. Values cannot be removed through the API. An existing value "
            "returns VALUE_EXISTS. " + _OWNERSHIP_NOTE
        ),
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def add_device_setting_value(
        setting: Literal["scan-interval", "windows-update-source"],
        interval_minutes: int | None = None,
        wsus_server_url: str | None = None,
        org_uuid: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        cached = await check_idempotency(request_id, "add_device_setting_value")
        if cached is not None:
            return cached
        params = {
            "org_uuid": org_uuid,
            "setting": setting,
            "interval_minutes": interval_minutes,
            "wsus_server_url": wsus_server_url,
        }
        try:
            result = await call_tool_workflow(
                client,
                workflows.add_device_setting_value,
                params,
                params_model=AddDeviceSettingValueParams,
                org_uuid_field="org_uuid",
                dump_mode="json",
            )
        except BaseException:
            await release_idempotency(request_id, "add_device_setting_value")
            raise
        await store_idempotency(request_id, "add_device_setting_value", result)
        return result

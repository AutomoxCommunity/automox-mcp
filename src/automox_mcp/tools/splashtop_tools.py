"""Splashtop Remote Control tools for Automox MCP.

Exposes the ten ``/remotecontrol-st/...`` endpoints Automox shipped on
2026-01-14. Read-only tools (device status, session status, attended
access lookup) are always registered; write tools are gated by
``read_only=False`` and carry ``destructiveHint: true``. The fleet-scale
``splashtop_bulk_install_uninstall`` is additionally env-gated behind
``AUTOMOX_MCP_ALLOW_SPLASHTOP_BULK_INSTALL_UNINSTALL`` (default off): one
call touches an entire server group, a blast radius per-call confirmation
cannot vet.

Why initiate_connection isn't gated more strictly: the API only returns
a ``splashtop-sos://...`` deeplink. The actual session does not start
until the operator's local Splashtop RMM App opens the URL, and if
attended access is enabled on the device, the end user must still
approve. We still mark it destructive because it produces operator-
actionable state and consumes session slots; agentic invocation should
require a human in the loop.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..client import AutomoxClient
from ..schemas import (
    SplashtopAttendedAccessGetParams,
    SplashtopBulkActionParams,
    SplashtopDeviceStatusParams,
    SplashtopForceDisconnectParams,
    SplashtopInitiateConnectionParams,
    SplashtopInstallParams,
    SplashtopSessionStatusParams,
    SplashtopSetAttendedAccessParams,
    SplashtopSetBulkAttendedAccessParams,
    SplashtopUninstallParams,
)
from ..utils.tooling import (
    call_tool_workflow,
    check_idempotency,
    is_splashtop_bulk_allowed,
    maybe_format_markdown,
    release_idempotency,
    store_idempotency,
)
from ..workflows.splashtop import (
    bulk_install_uninstall as _bulk_install_uninstall,
)
from ..workflows.splashtop import (
    force_disconnect as _force_disconnect,
)
from ..workflows.splashtop import (
    get_attended_access as _get_attended_access,
)
from ..workflows.splashtop import (
    get_device_status as _get_device_status,
)
from ..workflows.splashtop import (
    get_session_status as _get_session_status,
)
from ..workflows.splashtop import (
    initiate_connection as _initiate_connection,
)
from ..workflows.splashtop import (
    install_splashtop as _install_splashtop,
)
from ..workflows.splashtop import (
    set_attended_access as _set_attended_access,
)
from ..workflows.splashtop import (
    set_bulk_attended_access as _set_bulk_attended_access,
)
from ..workflows.splashtop import (
    uninstall_splashtop as _uninstall_splashtop,
)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register Splashtop Remote Control tools."""

    @server.tool(
        name="splashtop_device_status",
        description=(
            "List Splashtop installation and registration status for a device. "
            "Returns install_time, registration_status, and any install error."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def splashtop_device_status(
        device_uuid: str,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            _get_device_status,
            {"device_uuid": device_uuid},
            params_model=SplashtopDeviceStatusParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="splashtop_session_status",
        description=(
            "List active Splashtop remote-control sessions for a device. "
            "Returns can_start_new_session, current_sessions, and max_sessions."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def splashtop_session_status(
        device_uuid: str,
        account_type: str | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"device_uuid": device_uuid}
        if account_type is not None:
            params["account_type"] = account_type
        result = await call_tool_workflow(
            client,
            _get_session_status,
            params,
            params_model=SplashtopSessionStatusParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="splashtop_get_attended_access",
        description=(
            "Get the current attended-access requirement for a device. "
            "When requiredAttendedAccess is true, the end user must approve "
            "before a remote-control session can start."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def splashtop_get_attended_access(
        device_uuid: str,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            _get_attended_access,
            {"device_uuid": device_uuid},
            params_model=SplashtopAttendedAccessGetParams,
        )
        return maybe_format_markdown(result, output_format)

    if not read_only:

        @server.tool(
            name="splashtop_install",
            description=(
                "Install the Splashtop RMM client on a device. The install runs "
                "asynchronously. Use 'request_permission' to control whether the "
                "user is prompted at install time (distinct from per-session "
                "attended access). Requires a Remote Control subscription."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
        async def splashtop_install(
            device_uuid: str,
            os_family: str,
            request_permission: str | None = None,
            organization_uuid: str | None = None,
            account_type: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "splashtop_install")
            if cached is not None:
                return cached

            params: dict[str, Any] = {"device_uuid": device_uuid, "os_family": os_family}
            if request_permission is not None:
                params["request_permission"] = request_permission
            if organization_uuid is not None:
                params["organization_uuid"] = organization_uuid
            if account_type is not None:
                params["account_type"] = account_type
            try:
                result = await call_tool_workflow(
                    client,
                    _install_splashtop,
                    params,
                    params_model=SplashtopInstallParams,
                )
            except BaseException:
                await release_idempotency(request_id, "splashtop_install")
                raise
            await store_idempotency(request_id, "splashtop_install", result)
            return result

        # Fleet-scale Splashtop client deployment is opt-in beyond write mode: a
        # single call installs/uninstalls the Splashtop client across an entire
        # server group, a blast radius per-call confirmation cannot meaningfully
        # vet. Gated by AUTOMOX_MCP_ALLOW_SPLASHTOP_BULK_INSTALL_UNINSTALL.
        # Single-device Splashtop actions stay confirmation-gated only.
        if is_splashtop_bulk_allowed():

            @server.tool(
                name="splashtop_bulk_install_uninstall",
                description=(
                    "Asynchronously install or uninstall the Splashtop RMM client "
                    "across an entire server group in one call. Returns 200 when the "
                    "operation is queued (not when complete). Requires "
                    "AUTOMOX_MCP_ALLOW_SPLASHTOP_BULK_INSTALL_UNINSTALL=true."
                ),
                annotations={
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": False,
                    "openWorldHint": True,
                },
            )
            async def splashtop_bulk_install_uninstall(
                action: str,
                server_group_id: int | None = None,
                request_id: str | None = None,
            ) -> dict[str, Any]:
                cached = await check_idempotency(request_id, "splashtop_bulk_install_uninstall")
                if cached is not None:
                    return cached

                params: dict[str, Any] = {"action": action}
                if server_group_id is not None:
                    params["server_group_id"] = server_group_id
                try:
                    result = await call_tool_workflow(
                        client,
                        _bulk_install_uninstall,
                        params,
                        params_model=SplashtopBulkActionParams,
                    )
                except BaseException:
                    await release_idempotency(request_id, "splashtop_bulk_install_uninstall")
                    raise
                await store_idempotency(request_id, "splashtop_bulk_install_uninstall", result)
                return result

        @server.tool(
            name="splashtop_initiate_connection",
            description=(
                "Generate a Splashtop deeplink (splashtop-sos://...) for an "
                "operator to start a remote-control session. The API does NOT "
                "start the session itself — the operator must open the returned "
                "URL in their local Splashtop RMM App, and end-user consent "
                "still applies if attended access is enabled on the device."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
        async def splashtop_initiate_connection(
            device_uuid: str,
            os_family: str,
            connection_type: str,
            account_type: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "splashtop_initiate_connection")
            if cached is not None:
                return cached

            params: dict[str, Any] = {
                "device_uuid": device_uuid,
                "os_family": os_family,
                "connection_type": connection_type,
            }
            if account_type is not None:
                params["account_type"] = account_type
            try:
                result = await call_tool_workflow(
                    client,
                    _initiate_connection,
                    params,
                    params_model=SplashtopInitiateConnectionParams,
                )
            except BaseException:
                await release_idempotency(request_id, "splashtop_initiate_connection")
                raise
            await store_idempotency(request_id, "splashtop_initiate_connection", result)
            return result

        @server.tool(
            name="splashtop_force_disconnect",
            description=(
                "Force-disconnect ALL active Splashtop sessions on a device. "
                "Interrupts any in-progress operator work. Use sparingly."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def splashtop_force_disconnect(
            device_uuid: str,
            os_family: str,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "splashtop_force_disconnect")
            if cached is not None:
                return cached

            try:
                result = await call_tool_workflow(
                    client,
                    _force_disconnect,
                    {"device_uuid": device_uuid, "os_family": os_family},
                    params_model=SplashtopForceDisconnectParams,
                )
            except BaseException:
                await release_idempotency(request_id, "splashtop_force_disconnect")
                raise
            await store_idempotency(request_id, "splashtop_force_disconnect", result)
            return result

        @server.tool(
            name="splashtop_set_attended_access",
            description=(
                "Enable or disable the end-user consent requirement for "
                "Splashtop sessions on a device. Setting this to false allows "
                "unattended sessions — review your organization's policy before "
                "doing so."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def splashtop_set_attended_access(
            device_uuid: str,
            required_attended_access: bool,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "splashtop_set_attended_access")
            if cached is not None:
                return cached

            try:
                result = await call_tool_workflow(
                    client,
                    _set_attended_access,
                    {
                        "device_uuid": device_uuid,
                        "required_attended_access": required_attended_access,
                    },
                    params_model=SplashtopSetAttendedAccessParams,
                )
            except BaseException:
                await release_idempotency(request_id, "splashtop_set_attended_access")
                raise
            await store_idempotency(request_id, "splashtop_set_attended_access", result)
            return result

        @server.tool(
            name="splashtop_set_bulk_attended_access",
            description=(
                "Bulk-set the attended-access requirement across many devices. "
                "Setting required_attended_access=false on a list disables "
                "end-user consent on all of them at once — confirm before use."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def splashtop_set_bulk_attended_access(
            device_uuids: list[str],
            required_attended_access: bool,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "splashtop_set_bulk_attended_access")
            if cached is not None:
                return cached

            try:
                result = await call_tool_workflow(
                    client,
                    _set_bulk_attended_access,
                    {
                        "device_uuids": device_uuids,
                        "required_attended_access": required_attended_access,
                    },
                    params_model=SplashtopSetBulkAttendedAccessParams,
                )
            except BaseException:
                await release_idempotency(request_id, "splashtop_set_bulk_attended_access")
                raise
            await store_idempotency(request_id, "splashtop_set_bulk_attended_access", result)
            return result

        @server.tool(
            name="splashtop_uninstall",
            description=(
                "Uninstall the Splashtop RMM client from a device and delete "
                "its registration + attended-access setting. Permanent."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def splashtop_uninstall(
            device_uuid: str,
            os_family: str,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "splashtop_uninstall")
            if cached is not None:
                return cached

            try:
                result = await call_tool_workflow(
                    client,
                    _uninstall_splashtop,
                    {"device_uuid": device_uuid, "os_family": os_family},
                    params_model=SplashtopUninstallParams,
                )
            except BaseException:
                await release_idempotency(request_id, "splashtop_uninstall")
                raise
            await store_idempotency(request_id, "splashtop_uninstall", result)
            return result


__all__ = ["register"]

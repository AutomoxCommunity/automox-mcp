"""Policy windows (maintenance/exclusion windows) tools for Automox MCP."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastmcp import FastMCP
from pydantic import Field, field_validator

from .. import workflows
from ..client import AutomoxClient
from ..schemas import ForbidExtraModel
from ..utils.tooling import (
    call_tool_workflow,
    check_idempotency,
    maybe_format_markdown,
    store_idempotency,
)

# -----------------------------------------------------------------
# RRULE grammar (live-verified 2026-06-05): the upstream validator does NOT
# accept generic RFC 5545. It enforces exactly two grammars; FREQ=WEEKLY (and
# any other FREQ for recurring) is rejected with a 400.
#   recurrence=once     -> FREQ=DAILY;UNTIL=YYYYMMDDTHHMMSSZ  (compact UNTIL,
#                          no COUNT)
#   recurrence=recurring-> FREQ=YEARLY;BYMONTH=<1-12>;BYDAY=<+N weekday> only
# -----------------------------------------------------------------
_RRULE_GRAMMAR_NOTE = (
    "The 'rrule' field does NOT accept generic RFC 5545; the upstream "
    "validator enforces exactly two grammars (live-verified 2026-06-05). "
    "For recurrence=once: FREQ=DAILY;UNTIL=YYYYMMDDTHHMMSSZ (compact UNTIL, "
    "no COUNT). For recurrence=recurring: FREQ=YEARLY;BYMONTH=<1-12>;"
    "BYDAY=<+N weekday> only — no other FREQ values, no WEEKLY."
)

_RRULE_FIELD_DESCRIPTION = (
    "RRULE string. Validator-constrained, NOT generic RFC 5545: "
    "recurrence=once requires FREQ=DAILY;UNTIL=YYYYMMDDTHHMMSSZ; "
    "recurrence=recurring requires FREQ=YEARLY;BYMONTH=<1-12>;BYDAY=<+N "
    "weekday> only (FREQ=WEEKLY is rejected with a 400)."
)

_DTSTART_FIELD_DESCRIPTION = (
    "Start datetime, ISO 8601 (e.g. 2026-01-01T02:00:00Z). When "
    "use_local_tz=false this is UTC; when use_local_tz=true the same "
    "wall-clock is applied in each device's local timezone."
)


# -----------------------------------------------------------------
# Pydantic parameter models
# -----------------------------------------------------------------


class SearchPolicyWindowsParams(ForbidExtraModel):
    org_uuid: UUID
    group_uuids: list[UUID] | None = None
    statuses: list[Literal["active", "inactive"]] | None = None
    recurrences: list[Literal["recurring", "once"]] | None = None
    page: int | None = Field(None, ge=0, le=100)
    size: int | None = Field(None, ge=1, le=500)
    sort: str | None = Field(None, max_length=50)
    direction: Literal["asc", "desc"] | None = None


class GetPolicyWindowParams(ForbidExtraModel):
    org_uuid: UUID
    window_uuid: UUID


class CheckGroupExclusionStatusParams(ForbidExtraModel):
    org_uuid: UUID
    group_uuids: list[UUID]


class CheckWindowActiveParams(ForbidExtraModel):
    org_uuid: UUID
    window_uuid: UUID


# ISO 8601 date or date-time. Accepts:
#   YYYY-MM-DD                       (date only)
#   YYYY-MM-DDTHH:MM[:SS]            (local time)
#   YYYY-MM-DDTHH:MM[:SS].sss        (with sub-second precision)
#   YYYY-MM-DDTHH:MM[:SS][.sss]Z         (UTC)
#   YYYY-MM-DDTHH:MM[:SS][.sss]+HH:MM    (with offset)
#
# Previous regex was tighter (`^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?Z?)?$`)
# and silently rejected ISO 8601 strings with milliseconds or offsets — both
# common outputs from `datetime.isoformat()` and JS `Date.toISOString()`.
# Loosened to accept the standard ISO 8601 surface so the schema reflects
# what callers actually emit. Upstream date-format quirks documented per
# field below — see issue #78.
_ISO_DATE_OR_DATETIME = (
    r"^\d{4}-\d{2}-\d{2}"
    r"(T\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}:\d{2})?)?$"
)


# Known upstream quirk (issue #78): the /policy-windows/.../scheduled-windows
# endpoints declare `date` optional but treat it as required, and reject any
# format containing URL-encoded colons (i.e., the format every standard HTTP
# client emits). The Automox API error message says "Expected format:
# YYYY-MM-DDTHH:mm:ss" but in practice rejects that too. Until upstream is
# fixed, omitting `date` is the most reliable path; callers who must pass
# one should expect a 400 from the upstream.
_SCHEDULED_WINDOWS_DATE_DESCRIPTION = (
    "Optional ISO 8601 date or date-time. Note: the upstream Automox API "
    "currently has a known bug where this parameter is rejected for most "
    "formats including the one documented in its own error message; omit "
    "this parameter unless you have a tenant-specific reason to set it. "
    "Tracked as issue #78."
)


class GetGroupScheduledWindowsParams(ForbidExtraModel):
    org_uuid: UUID
    group_uuid: UUID
    date: str | None = Field(
        None,
        pattern=_ISO_DATE_OR_DATETIME,
        description=_SCHEDULED_WINDOWS_DATE_DESCRIPTION,
    )


class GetDeviceScheduledWindowsParams(ForbidExtraModel):
    org_uuid: UUID
    device_uuid: UUID
    date: str | None = Field(
        None,
        pattern=_ISO_DATE_OR_DATETIME,
        description=_SCHEDULED_WINDOWS_DATE_DESCRIPTION,
    )


class CreatePolicyWindowParams(ForbidExtraModel):
    org_uuid: UUID
    window_type: Literal["exclude"] = Field(description="Window type")
    window_name: str = Field(max_length=100)
    window_description: str = Field(max_length=500)
    rrule: str = Field(description=_RRULE_FIELD_DESCRIPTION)
    duration_minutes: int = Field(gt=0, le=43200)
    use_local_tz: bool
    recurrence: Literal["recurring", "once"]
    group_uuids: list[UUID]
    dtstart: str = Field(
        description=_DTSTART_FIELD_DESCRIPTION,
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z?$",
    )
    status: Literal["active", "inactive"]

    @field_validator("rrule")
    @classmethod
    def validate_rrule(cls, v: str) -> str:
        if not v.startswith("FREQ="):
            raise ValueError(
                "rrule must start with 'FREQ=' (FREQ=DAILY for once; FREQ=YEARLY for recurring)"
            )
        if len(v) > 500:
            raise ValueError("rrule must not exceed 500 characters")
        return v


class UpdatePolicyWindowParams(ForbidExtraModel):
    org_uuid: UUID
    window_uuid: UUID
    dtstart: str = Field(
        description="Start datetime (required by API)",
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z?$",
    )
    window_type: Literal["exclude"] | None = None
    window_name: str | None = Field(None, max_length=100)
    window_description: str | None = Field(None, max_length=500)
    rrule: str | None = Field(None, description=_RRULE_FIELD_DESCRIPTION)
    duration_minutes: int | None = Field(None, gt=0, le=43200)
    use_local_tz: bool | None = None
    recurrence: Literal["recurring", "once"] | None = None
    group_uuids: list[UUID] | None = None
    status: Literal["active", "inactive"] | None = None

    @field_validator("rrule")
    @classmethod
    def validate_rrule(cls, v: str | None) -> str | None:
        if v is not None:
            if not v.startswith("FREQ="):
                raise ValueError(
                    "rrule must start with 'FREQ=' (FREQ=DAILY for once; FREQ=YEARLY for recurring)"
                )
            if len(v) > 500:
                raise ValueError("rrule must not exceed 500 characters")
        return v


class DeletePolicyWindowParams(ForbidExtraModel):
    org_uuid: UUID
    window_uuid: UUID


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register policy windows (maintenance windows) tools."""

    # ------ Read-only tools (always registered) ------

    @server.tool(
        name="search_policy_windows",
        description=(
            "Search and list maintenance/exclusion windows for the Automox organization. "
            "Supports filtering by group UUIDs, status (active/inactive), and recurrence "
            "type (recurring/once). Supports pagination via page/size."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def search_policy_windows(
        org_uuid: str | None = None,
        group_uuids: list[str] | None = None,
        statuses: list[str] | None = None,
        recurrences: list[str] | None = None,
        page: int | None = None,
        size: int | None = None,
        sort: str | None = None,
        direction: str | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "org_uuid": org_uuid,
            "group_uuids": group_uuids,
            "statuses": statuses,
            "recurrences": recurrences,
            "page": page,
            "size": size,
            "sort": sort,
            "direction": direction,
        }
        result = await call_tool_workflow(
            client,
            workflows.search_policy_windows,
            params,
            params_model=SearchPolicyWindowsParams,
            org_uuid_field="org_uuid",
            dump_mode="json",
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_policy_window",
        description=(
            "Retrieve details for a specific maintenance/exclusion window by UUID. "
            "Returns status (lowercase active | inactive) and recurrence (UPPERCASE "
            "ONCE | RECURRING on read)."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_policy_window(
        window_uuid: str,
        org_uuid: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "org_uuid": org_uuid,
            "window_uuid": window_uuid,
        }
        return await call_tool_workflow(
            client,
            workflows.get_policy_window,
            params,
            params_model=GetPolicyWindowParams,
            org_uuid_field="org_uuid",
            dump_mode="json",
        )

    @server.tool(
        name="check_group_exclusion_status",
        description=(
            "Check whether one or more server groups are currently within an active "
            "exclusion window. Returns a per-group boolean status."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def check_group_exclusion_status(
        group_uuids: list[str],
        org_uuid: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "org_uuid": org_uuid,
            "group_uuids": group_uuids,
        }
        return await call_tool_workflow(
            client,
            workflows.check_group_exclusion_status,
            params,
            params_model=CheckGroupExclusionStatusParams,
            org_uuid_field="org_uuid",
            dump_mode="json",
        )

    @server.tool(
        name="check_window_active",
        description=(
            "Check whether a specific maintenance window is currently active. "
            "A window is active when its status is 'active', it has at least one "
            "group, and the current time falls within an exclusion period."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def check_window_active(
        window_uuid: str,
        org_uuid: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "org_uuid": org_uuid,
            "window_uuid": window_uuid,
        }
        return await call_tool_workflow(
            client,
            workflows.check_window_active,
            params,
            params_model=CheckWindowActiveParams,
            org_uuid_field="org_uuid",
            dump_mode="json",
        )

    @server.tool(
        name="get_group_scheduled_windows",
        description=(
            "Get upcoming scheduled maintenance periods for a server group. "
            "Returns start/end times and window types. Optionally provide a "
            "future date limit (ISO 8601 UTC). start/end are derived occurrence "
            "times (the window stores dtstart+duration_minutes+rrule, not "
            "start/end); their timezone basis follows the window's use_local_tz."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_group_scheduled_windows(
        group_uuid: str,
        org_uuid: str | None = None,
        date: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "org_uuid": org_uuid,
            "group_uuid": group_uuid,
            "date": date,
        }
        return await call_tool_workflow(
            client,
            workflows.get_group_scheduled_windows,
            params,
            params_model=GetGroupScheduledWindowsParams,
            org_uuid_field="org_uuid",
            dump_mode="json",
        )

    @server.tool(
        name="get_device_scheduled_windows",
        description=(
            "Get upcoming scheduled maintenance periods for a specific device. "
            "Returns start/end times and window types. Optionally provide a "
            "future date limit (ISO 8601 UTC). start/end are derived occurrence "
            "times (the window stores dtstart+duration_minutes+rrule, not "
            "start/end); their timezone basis follows the window's use_local_tz."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_device_scheduled_windows(
        device_uuid: str,
        org_uuid: str | None = None,
        date: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "org_uuid": org_uuid,
            "device_uuid": device_uuid,
            "date": date,
        }
        return await call_tool_workflow(
            client,
            workflows.get_device_scheduled_windows,
            params,
            params_model=GetDeviceScheduledWindowsParams,
            org_uuid_field="org_uuid",
            dump_mode="json",
        )

    # ------ Write tools (gated by read_only) ------

    if not read_only:

        @server.tool(
            name="create_policy_window",
            description=(
                "Create a new maintenance/exclusion window that prevents policy "
                "execution on the specified groups during the defined periods. "
                "All fields are required. " + _RRULE_GRAMMAR_NOTE + " status "
                "accepts active|inactive; recurrence accepts once|recurring "
                "(lowercase on input)."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
        async def create_policy_window(
            window_type: str,
            window_name: str,
            window_description: str,
            rrule: str,
            duration_minutes: int,
            use_local_tz: bool,
            recurrence: str,
            group_uuids: list[str],
            dtstart: str,
            status: str,
            org_uuid: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "create_policy_window")
            if cached is not None:
                return cached

            params = {
                "org_uuid": org_uuid,
                "window_type": window_type,
                "window_name": window_name,
                "window_description": window_description,
                "rrule": rrule,
                "duration_minutes": duration_minutes,
                "use_local_tz": use_local_tz,
                "recurrence": recurrence,
                "group_uuids": group_uuids,
                "dtstart": dtstart,
                "status": status,
            }
            result = await call_tool_workflow(
                client,
                workflows.create_policy_window,
                params,
                params_model=CreatePolicyWindowParams,
                org_uuid_field="org_uuid",
                dump_mode="json",
            )
            await store_idempotency(request_id, "create_policy_window", result)
            return result

        @server.tool(
            name="update_policy_window",
            description=(
                "Update an existing maintenance window. Only dtstart is required; "
                "all other fields are optional for partial updates. status is "
                "lowercase active | inactive; recurrence is lowercase once | "
                "recurring on input. " + _RRULE_GRAMMAR_NOTE
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def update_policy_window(
            window_uuid: str,
            dtstart: str,
            org_uuid: str | None = None,
            window_type: str | None = None,
            window_name: str | None = None,
            window_description: str | None = None,
            rrule: str | None = None,
            duration_minutes: int | None = None,
            use_local_tz: bool | None = None,
            recurrence: str | None = None,
            group_uuids: list[str] | None = None,
            status: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "update_policy_window")
            if cached is not None:
                return cached

            params = {
                "org_uuid": org_uuid,
                "window_uuid": window_uuid,
                "dtstart": dtstart,
                "window_type": window_type,
                "window_name": window_name,
                "window_description": window_description,
                "rrule": rrule,
                "duration_minutes": duration_minutes,
                "use_local_tz": use_local_tz,
                "recurrence": recurrence,
                "group_uuids": group_uuids,
                "status": status,
            }
            result = await call_tool_workflow(
                client,
                workflows.update_policy_window,
                params,
                params_model=UpdatePolicyWindowParams,
                org_uuid_field="org_uuid",
                dump_mode="json",
            )
            await store_idempotency(request_id, "update_policy_window", result)
            return result

        @server.tool(
            name="delete_policy_window",
            description="Delete a maintenance/exclusion window permanently.",
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def delete_policy_window(
            window_uuid: str,
            org_uuid: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "delete_policy_window")
            if cached is not None:
                return cached

            params = {
                "org_uuid": org_uuid,
                "window_uuid": window_uuid,
            }
            result = await call_tool_workflow(
                client,
                workflows.delete_policy_window,
                params,
                params_model=DeletePolicyWindowParams,
                org_uuid_field="org_uuid",
                dump_mode="json",
            )
            await store_idempotency(request_id, "delete_policy_window", result)
            return result


__all__ = ["register"]

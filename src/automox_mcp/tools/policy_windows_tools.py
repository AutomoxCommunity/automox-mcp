"""Policy windows (maintenance/exclusion windows) tools for Automox MCP."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field, ValidationError, field_validator

from .. import workflows
from ..client import AutomoxAPIError, AutomoxClient
from ..schemas import ForbidExtraModel
from ..utils import resolve_org_uuid
from ..utils.tooling import (
    RateLimitError,
    as_tool_response,
    check_idempotency,
    enforce_rate_limit,
    format_error,
    format_validation_error,
    maybe_format_markdown,
    store_idempotency,
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


class GetGroupScheduledWindowsParams(ForbidExtraModel):
    org_uuid: UUID
    group_uuid: UUID
    date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?Z?)?$")


class GetDeviceScheduledWindowsParams(ForbidExtraModel):
    org_uuid: UUID
    device_uuid: UUID
    date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?Z?)?$")


class CreatePolicyWindowParams(ForbidExtraModel):
    org_uuid: UUID
    window_type: Literal["exclude"] = Field(description="Window type")
    window_name: str = Field(max_length=100)
    window_description: str = Field(max_length=500)
    rrule: str = Field(description="RFC 5545 RRULE string")
    duration_minutes: int = Field(gt=0, le=43200)
    use_local_tz: bool
    recurrence: Literal["recurring", "once"]
    group_uuids: list[UUID]
    dtstart: str = Field(
        description="Start datetime in ISO 8601 UTC format",
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z?$",
    )
    status: Literal["active", "inactive"]

    @field_validator("rrule")
    @classmethod
    def validate_rrule(cls, v: str) -> str:
        if not v.startswith("FREQ="):
            raise ValueError("rrule must start with 'FREQ=' per RFC 5545")
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
    rrule: str | None = None
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
                raise ValueError("rrule must start with 'FREQ=' per RFC 5545")
            if len(v) > 500:
                raise ValueError("rrule must not exceed 500 characters")
        return v


class DeletePolicyWindowParams(ForbidExtraModel):
    org_uuid: UUID
    window_uuid: UUID


logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register policy windows (maintenance windows) tools."""

    async def _call(
        func: Callable[..., Awaitable[dict[str, Any]]],
        params_model: type[BaseModel] | None,
        raw_params: dict[str, Any],
        org_uuid_field: str | None = None,
    ) -> dict[str, Any]:
        try:
            await enforce_rate_limit()
            client_org_id = client.org_id
            params = dict(raw_params)
            if org_uuid_field is not None:
                raw_org_id = params.get("org_id")
                resolved_uuid = await resolve_org_uuid(
                    client,
                    explicit_uuid=params.get(org_uuid_field),
                    org_id=raw_org_id if raw_org_id is not None else client_org_id,
                    allow_account_uuid=True,
                )
                params[org_uuid_field] = resolved_uuid
            if params_model is not None:
                model = params_model(**params)
                payload = model.model_dump(mode="json", exclude_none=True)
            else:
                payload = {k: v for k, v in params.items() if v is not None}
            result: dict[str, Any] = await func(client, **payload)
        except (ValidationError, ValueError) as exc:
            raise ToolError(format_validation_error(exc)) from exc
        except RateLimitError as exc:
            raise ToolError(str(exc)) from exc
        except AutomoxAPIError as exc:
            raise ToolError(format_error(exc)) from exc
        except ToolError:
            raise
        except Exception as exc:
            logger.exception("Unexpected error in tool call")
            raise ToolError("An internal error occurred. Check server logs for details.") from exc
        return as_tool_response(result)

    # ------ Read-only tools (always registered) ------

    @server.tool(
        name="search_policy_windows",
        description=(
            "Search and list maintenance/exclusion windows for the Automox organization. "
            "Supports filtering by group UUIDs, status (active/inactive), and recurrence "
            "type (recurring/once). Supports pagination via page/size."
        ),
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
        result = await _call(
            workflows.search_policy_windows,
            SearchPolicyWindowsParams,
            params,
            org_uuid_field="org_uuid",
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_policy_window",
        description="Retrieve details for a specific maintenance/exclusion window by UUID.",
    )
    async def get_policy_window(
        window_uuid: str,
        org_uuid: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "org_uuid": org_uuid,
            "window_uuid": window_uuid,
        }
        return await _call(
            workflows.get_policy_window,
            GetPolicyWindowParams,
            params,
            org_uuid_field="org_uuid",
        )

    @server.tool(
        name="check_group_exclusion_status",
        description=(
            "Check whether one or more server groups are currently within an active "
            "exclusion window. Returns a per-group boolean status."
        ),
    )
    async def check_group_exclusion_status(
        group_uuids: list[str],
        org_uuid: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "org_uuid": org_uuid,
            "group_uuids": group_uuids,
        }
        return await _call(
            workflows.check_group_exclusion_status,
            CheckGroupExclusionStatusParams,
            params,
            org_uuid_field="org_uuid",
        )

    @server.tool(
        name="check_window_active",
        description=(
            "Check whether a specific maintenance window is currently active. "
            "A window is active when its status is 'active', it has at least one "
            "group, and the current time falls within an exclusion period."
        ),
    )
    async def check_window_active(
        window_uuid: str,
        org_uuid: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "org_uuid": org_uuid,
            "window_uuid": window_uuid,
        }
        return await _call(
            workflows.check_window_active,
            CheckWindowActiveParams,
            params,
            org_uuid_field="org_uuid",
        )

    @server.tool(
        name="get_group_scheduled_windows",
        description=(
            "Get upcoming scheduled maintenance periods for a server group. "
            "Returns start/end times and window types. Optionally provide a "
            "future date limit (ISO 8601 UTC)."
        ),
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
        return await _call(
            workflows.get_group_scheduled_windows,
            GetGroupScheduledWindowsParams,
            params,
            org_uuid_field="org_uuid",
        )

    @server.tool(
        name="get_device_scheduled_windows",
        description=(
            "Get upcoming scheduled maintenance periods for a specific device. "
            "Returns start/end times and window types. Optionally provide a "
            "future date limit (ISO 8601 UTC)."
        ),
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
        return await _call(
            workflows.get_device_scheduled_windows,
            GetDeviceScheduledWindowsParams,
            params,
            org_uuid_field="org_uuid",
        )

    # ------ Write tools (gated by read_only) ------

    if not read_only:

        @server.tool(
            name="create_policy_window",
            description=(
                "Create a new maintenance/exclusion window. Uses RFC 5545 RRULE "
                "for scheduling. All fields are required. The window prevents "
                "policy execution on the specified groups during the defined periods."
            ),
            annotations={"destructiveHint": True},
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
            result = await _call(
                workflows.create_policy_window,
                CreatePolicyWindowParams,
                params,
                org_uuid_field="org_uuid",
            )
            await store_idempotency(request_id, "create_policy_window", result)
            return result

        @server.tool(
            name="update_policy_window",
            description=(
                "Update an existing maintenance window. Only dtstart is required; "
                "all other fields are optional for partial updates."
            ),
            annotations={"destructiveHint": True},
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
            result = await _call(
                workflows.update_policy_window,
                UpdatePolicyWindowParams,
                params,
                org_uuid_field="org_uuid",
            )
            await store_idempotency(request_id, "update_policy_window", result)
            return result

        @server.tool(
            name="delete_policy_window",
            description="Delete a maintenance/exclusion window permanently.",
            annotations={"destructiveHint": True},
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
            result = await _call(
                workflows.delete_policy_window,
                DeletePolicyWindowParams,
                params,
                org_uuid_field="org_uuid",
            )
            await store_idempotency(request_id, "delete_policy_window", result)
            return result


__all__ = ["register"]

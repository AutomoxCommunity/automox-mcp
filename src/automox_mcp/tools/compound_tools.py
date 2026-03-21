"""Compound tools that combine multiple API calls into single high-value responses."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from .. import workflows
from ..client import AutomoxAPIError, AutomoxClient
from ..schemas import OrgIdContextMixin, OrgIdRequiredMixin
from ..utils import resolve_org_uuid
from ..utils.tooling import (
    RateLimitError,
    as_tool_response,
    enforce_rate_limit,
    format_error,
)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register compound tools."""

    async def _call(
        func: Callable[..., Awaitable[dict[str, Any]]],
        raw_params: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            await enforce_rate_limit()
            client_org_id = client.org_id
            if client_org_id is None:
                raise ToolError(
                    "org_id required - set AUTOMOX_ORG_ID or pass org_id explicitly."
                )
            raw_params["org_id"] = client_org_id
            result: dict[str, Any] = await func(client, **raw_params)
        except (ValidationError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        except RateLimitError as exc:
            raise ToolError(str(exc)) from exc
        except AutomoxAPIError as exc:
            raise ToolError(format_error(exc)) from exc
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"Unexpected error: {type(exc).__name__}: {exc}") from exc
        return as_tool_response(result)

    async def _call_with_org_uuid(
        func: Callable[..., Awaitable[dict[str, Any]]],
        raw_params: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            await enforce_rate_limit()
            client_org_id = client.org_id
            if client_org_id is None:
                raise ToolError(
                    "org_id required - set AUTOMOX_ORG_ID or pass org_id explicitly."
                )
            org_uuid = await resolve_org_uuid(
                client,
                org_id=client_org_id,
                allow_account_uuid=True,
            )
            raw_params["org_id"] = client_org_id
            raw_params["org_uuid"] = str(org_uuid)
            result: dict[str, Any] = await func(client, **raw_params)
        except (ValidationError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        except RateLimitError as exc:
            raise ToolError(str(exc)) from exc
        except AutomoxAPIError as exc:
            raise ToolError(format_error(exc)) from exc
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"Unexpected error: {type(exc).__name__}: {exc}") from exc
        return as_tool_response(result)

    @server.tool(
        name="get_patch_tuesday_readiness",
        description=(
            "Combined view of pre-patch report, pending approvals, and patch policy "
            "schedules. Answers 'Are we ready for Patch Tuesday?' in a single call."
        ),
    )
    async def get_patch_tuesday_readiness(
        group_id: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if group_id is not None:
            params["group_id"] = group_id
        return await _call_with_org_uuid(
            workflows.compound.get_patch_tuesday_readiness, params,
        )

    @server.tool(
        name="get_compliance_snapshot",
        description=(
            "Combined view of non-compliant devices, fleet health metrics, and "
            "policy statistics. Answers 'What is our compliance posture?' in a single call."
        ),
    )
    async def get_compliance_snapshot(
        group_id: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if group_id is not None:
            params["group_id"] = group_id
        return await _call(
            workflows.compound.get_compliance_snapshot, params,
        )

    @server.tool(
        name="get_device_full_profile",
        description=(
            "Complete device profile combining device detail, inventory summary, "
            "packages, and policy assignments in a single call. Inventory is "
            "summarized with key values per category. Packages capped at "
            "max_packages (default 25). Use get_device_inventory or "
            "list_device_packages for full data."
        ),
    )
    async def get_device_full_profile(
        device_id: int,
        max_packages: int = 25,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"device_id": device_id, "max_packages": max_packages}
        return await _call(
            workflows.compound.get_device_full_profile, params,
        )


__all__ = ["register"]

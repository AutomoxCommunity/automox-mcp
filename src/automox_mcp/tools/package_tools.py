"""Package-related tools for Automox MCP."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from .. import workflows
from ..client import AutomoxAPIError, AutomoxClient
from ..schemas import (
    GetDevicePackagesParams,
    GetOrganizationPackagesParams,
    OrgIdContextMixin,
    OrgIdRequiredMixin,
)
from ..utils.tooling import (
    RateLimitError,
    as_tool_response,
    enforce_rate_limit,
    format_error,
    format_validation_error,
    maybe_format_markdown,
)

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register package-related tools."""

    async def _call(
        func: Callable[..., Awaitable[dict[str, Any]]],
        params_model: type[BaseModel],
        raw_params: dict[str, Any],
        *,
        inject_org_id: bool = False,
    ) -> dict[str, Any]:
        try:
            await enforce_rate_limit()
            client_org_id = client.org_id
            params = dict(raw_params)
            if issubclass(params_model, (OrgIdContextMixin, OrgIdRequiredMixin)):
                params.setdefault("org_id", client_org_id)
                if params.get("org_id") is None:
                    raise ToolError(
                        "org_id required - set AUTOMOX_ORG_ID or pass org_id explicitly."
                    )
            model = params_model(**params)
            payload = model.model_dump(mode="python", exclude_none=True)
            if isinstance(model, (OrgIdContextMixin, OrgIdRequiredMixin)):
                payload["org_id"] = model.org_id
            elif inject_org_id:
                if client_org_id is None:
                    raise ToolError(
                        "org_id required - set AUTOMOX_ORG_ID or pass org_id explicitly."
                    )
                payload["org_id"] = client_org_id
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

    @server.tool(
        name="list_device_packages",
        description=(
            "List software packages installed on a specific Automox device. "
            "Returns package names, versions, patch status, and severity."
        ),
    )
    async def list_device_packages(
        device_id: int,
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "device_id": device_id,
            "page": page,
            "limit": limit,
        }
        result = await _call(
            workflows.list_device_packages,
            GetDevicePackagesParams,
            params,
            inject_org_id=True,
        )

        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="search_org_packages",
        description=(
            "Search software packages across the Automox organization. "
            "Filter by managed status or packages awaiting installation."
        ),
    )
    async def search_org_packages(
        include_unmanaged: bool | None = None,
        awaiting: bool | None = None,
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "include_unmanaged": include_unmanaged,
            "awaiting": awaiting,
            "page": page,
            "limit": limit,
        }
        result = await _call(
            workflows.search_org_packages,
            GetOrganizationPackagesParams,
            params,
        )

        return maybe_format_markdown(result, output_format)


__all__ = ["register"]

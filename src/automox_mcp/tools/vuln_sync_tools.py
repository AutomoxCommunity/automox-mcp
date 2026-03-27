"""Vulnerability Sync / Remediations tools for Automox MCP."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from ..client import AutomoxAPIError, AutomoxClient
from ..schemas import (
    GetActionSetIssuesParams,
    GetActionSetParams,
    GetActionSetSolutionsParams,
    GetActionSetUploadFormatsParams,
    ListActionSetsParams,
    OrgIdContextMixin,
    OrgIdRequiredMixin,
    UploadActionSetParams,
)
from ..utils.tooling import (
    RateLimitError,
    as_tool_response,
    check_idempotency,
    enforce_rate_limit,
    format_error,
    maybe_format_markdown,
    store_idempotency,
)
from ..workflows.vuln_sync import (
    get_action_set_actions as _get_action_set_actions,
)
from ..workflows.vuln_sync import (
    get_action_set_detail as _get_action_set_detail,
)
from ..workflows.vuln_sync import (
    get_action_set_issues as _get_action_set_issues,
)
from ..workflows.vuln_sync import (
    get_action_set_solutions as _get_action_set_solutions,
)
from ..workflows.vuln_sync import (
    get_upload_formats as _get_upload_formats,
)
from ..workflows.vuln_sync import (
    list_remediation_action_sets as _list_remediation_action_sets,
)
from ..workflows.vuln_sync import (
    upload_action_set as _upload_action_set,
)

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register vulnerability sync / remediations tools."""

    async def _call(
        func: Callable[..., Awaitable[dict[str, Any]]],
        params_model: type[BaseModel],
        raw_params: dict[str, Any],
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
            result: dict[str, Any] = await func(client, **payload)
        except (ValidationError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
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
        name="list_remediation_action_sets",
        description=(
            "List vulnerability remediation action sets for the organization. "
            "Shows imported vulnerability data and remediation tracking."
        ),
    )
    async def list_remediation_action_sets(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await _call(
            _list_remediation_action_sets,
            ListActionSetsParams,
            {},
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_action_set_detail",
        description="Get details for a specific vulnerability remediation action set.",
    )
    async def get_action_set_detail(
        action_set_id: int,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await _call(
            _get_action_set_detail,
            GetActionSetParams,
            {"action_set_id": action_set_id},
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_action_set_actions",
        description=(
            "Get remediation actions for a vulnerability action set. "
            "Shows what patches or changes need to be applied."
        ),
    )
    async def get_action_set_actions(
        action_set_id: int,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await _call(
            _get_action_set_actions,
            GetActionSetParams,
            {"action_set_id": action_set_id},
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_action_set_issues",
        description=(
            "Get vulnerability issues (CVEs) associated with an action set. "
            "Shows which vulnerabilities are being tracked for remediation."
        ),
    )
    async def get_action_set_issues(
        action_set_id: int,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await _call(
            _get_action_set_issues,
            GetActionSetIssuesParams,
            {"action_set_id": action_set_id},
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_action_set_solutions",
        description=(
            "Get solutions for a vulnerability action set. "
            "Shows recommended patches or configurations to resolve vulnerabilities."
        ),
    )
    async def get_action_set_solutions(
        action_set_id: int,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await _call(
            _get_action_set_solutions,
            GetActionSetSolutionsParams,
            {"action_set_id": action_set_id},
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_upload_formats",
        description="Get supported CSV upload formats for vulnerability remediation action sets.",
    )
    async def get_upload_formats(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await _call(
            _get_upload_formats,
            GetActionSetUploadFormatsParams,
            {},
        )
        return maybe_format_markdown(result, output_format)

    if not read_only:

        @server.tool(
            name="upload_action_set",
            description=(
                "Upload a CSV-based vulnerability remediation action set. "
                "Use get_upload_formats to see supported formats first."
            ),
        )
        async def upload_action_set(
            action_set_data: dict[str, Any],
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "upload_action_set")
            if cached is not None:
                return cached
            result = await _call(
                _upload_action_set,
                UploadActionSetParams,
                {"action_set_data": action_set_data},
            )
            await store_idempotency(request_id, "upload_action_set", result)
            return result


__all__ = ["register"]

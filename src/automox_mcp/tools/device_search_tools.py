"""Advanced device search tools (Server Groups API v2) for Automox MCP."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..client import AutomoxClient
from ..schemas import (
    AdvancedDeviceSearchParams,
    AssignPoliciesToSavedSearchParams,
    CachedSearchResultsParams,
    CreateSavedSearchParams,
    DeleteSavedSearchParams,
    DeviceByUuidParams,
    DeviceSearchTypeaheadParams,
    GetSavedSearchParams,
    RefreshSearchCacheParams,
    RunSavedSearchParams,
    SavedSearchResultsParams,
    SearchesByDeviceParams,
    UpdateSavedSearchParams,
)
from ..utils.tooling import (
    call_tool_workflow,
    check_idempotency,
    maybe_format_markdown,
    release_idempotency,
    store_idempotency,
)
from ..workflows.device_search import (
    advanced_device_search as _advanced_device_search,
)
from ..workflows.device_search import (
    assign_policies_to_saved_search as _assign_policies_to_saved_search,
)
from ..workflows.device_search import (
    create_saved_search as _create_saved_search,
)
from ..workflows.device_search import (
    delete_saved_search as _delete_saved_search,
)
from ..workflows.device_search import (
    device_search_typeahead as _device_search_typeahead,
)
from ..workflows.device_search import (
    get_cached_search_results as _get_cached_search_results,
)
from ..workflows.device_search import (
    get_device_assignments as _get_device_assignments,
)
from ..workflows.device_search import (
    get_device_by_uuid as _get_device_by_uuid,
)
from ..workflows.device_search import (
    get_device_metadata_fields as _get_device_metadata_fields,
)
from ..workflows.device_search import (
    get_saved_search as _get_saved_search,
)
from ..workflows.device_search import (
    get_saved_search_results as _get_saved_search_results,
)
from ..workflows.device_search import (
    get_search_scopes as _get_search_scopes,
)
from ..workflows.device_search import (
    get_searchable_fields as _get_searchable_fields,
)
from ..workflows.device_search import (
    list_saved_searches as _list_saved_searches,
)
from ..workflows.device_search import (
    list_searches_for_device as _list_searches_for_device,
)
from ..workflows.device_search import (
    refresh_saved_search_cache as _refresh_saved_search_cache,
)
from ..workflows.device_search import (
    run_saved_search as _run_saved_search,
)
from ..workflows.device_search import (
    update_saved_search as _update_saved_search,
)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register advanced device search tools."""

    @server.tool(
        name="list_saved_searches",
        description=(
            "List saved device searches from the Advanced Device Search API. "
            "Returns saved search names, queries, and metadata."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def list_saved_searches(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(client, _list_saved_searches, {})
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="advanced_device_search",
        description=(
            "Execute an advanced device search using the Automox Advanced Device "
            "Search API's structured query language. Enables complex queries like "
            "'find all Windows devices not seen in 30 days' or 'devices with nginx "
            "installed' using field-based filtering. Pass `query` as a dict with a "
            "`filters` list of AND/OR groups, each a list of conditions: "
            '`{"filters": [{"AND": [{"scope": "SOFTWARE", "field": '
            '"pkgDisplayName", "operator": "IN", "values": ["nginx"]}]}]}`. '
            'Tag search uses scope TAGS (not DEVICE): `{"scope": "TAGS", '
            '"field": "tag", "operator": "IN", "values": ["Nginx"]}`. '
            "Use `get_searchable_fields` for valid scope/field/operator combos "
            "and `device_search_typeahead` to discover values. The org is scoped "
            "automatically. `limit` sets the page size. Requires an org-scoped "
            "API key — a global/account key gets HTTP 403 on this endpoint."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def advanced_device_search(
        query: dict[str, Any] | None = None,
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            _advanced_device_search,
            {"query": query, "page": page, "limit": limit},
            params_model=AdvancedDeviceSearchParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="device_search_typeahead",
        description=(
            "Get typeahead suggestions for device search fields. "
            "Useful for discovering valid values when building advanced device queries."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def device_search_typeahead(
        field: str,
        prefix: str,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            _device_search_typeahead,
            {"field": field, "prefix": prefix},
            params_model=DeviceSearchTypeaheadParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_device_metadata_fields",
        description=(
            "Get available fields for device queries. "
            "Returns the field names and types supported by the advanced device search API."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_device_metadata_fields(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(client, _get_device_metadata_fields, {})
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_device_assignments",
        description=("Get device-to-policy and device-to-group assignments."),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_device_assignments(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(client, _get_device_assignments, {})
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_device_by_uuid",
        description=(
            "Get device details by UUID using the Server Groups API v2. "
            "Provides device information via UUID-based lookup."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_device_by_uuid(
        device_uuid: str,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            _get_device_by_uuid,
            {"device_uuid": device_uuid},
            params_model=DeviceByUuidParams,
        )
        return maybe_format_markdown(result, output_format)

    # ------------------------------------------------------------------
    # Saved-search CRUD + bulk-assignment (Device Explorer, 2025-12-11)
    # ------------------------------------------------------------------

    @server.tool(
        name="get_saved_search",
        description=(
            "Retrieve a single saved device search by ID. Returns the saved "
            "search name, description, query, and metadata."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_saved_search(
        saved_search_id: str,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            _get_saved_search,
            {"saved_search_id": saved_search_id},
            params_model=GetSavedSearchParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_saved_search_results",
        description=(
            "Execute a saved device search and retrieve its current device "
            "result set. Supports pagination via page + limit."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_saved_search_results(
        saved_search_id: str,
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            _get_saved_search_results,
            {"saved_search_id": saved_search_id, "page": page, "limit": limit},
            params_model=SavedSearchResultsParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_cached_search_results",
        description=(
            "Retrieve cached server-side results for a previously-executed "
            "device search, keyed by search execution ID. Distinct from "
            "get_saved_search_results which re-executes a saved-search "
            "definition."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_cached_search_results(
        search_id: str,
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            _get_cached_search_results,
            {"search_id": search_id, "page": page, "limit": limit},
            params_model=CachedSearchResultsParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_search_scopes",
        description=(
            "List available device-search scope options. Org-independent "
            "metadata describing the scopes (e.g., device, group, org) "
            "supported by the Advanced Device Search API."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_search_scopes(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(client, _get_search_scopes, {})
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_searchable_fields",
        description=(
            "List searchable device fields grouped by scope, with per-field type "
            "metadata. Richer than get_device_metadata_fields (a flat field-name "
            "array) — use this to construct typed advanced-search queries."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_searchable_fields(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(client, _get_searchable_fields, {})
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="list_searches_for_device",
        description=(
            "List the saved device searches whose result set currently contains a "
            "given device (by UUID). Triage primitive: 'which saved searches does "
            "this device match?' Optionally filter by saved-search type."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def list_searches_for_device(
        device_uuid: str,
        search_type: str | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            _list_searches_for_device,
            {"device_uuid": device_uuid, "search_type": search_type},
            params_model=SearchesByDeviceParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="run_saved_search",
        description=(
            "Execute a saved device search by UUID and return its device results, "
            "with paging (page/size) and an optional `fields` projection. "
            "Lighter-weight than get_saved_search_results when you only need a "
            "subset of fields."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def run_saved_search(
        search_id: str,
        page: int | None = None,
        size: int | None = None,
        fields: list[str] | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            _run_saved_search,
            {"search_id": search_id, "page": page, "size": size, "fields": fields},
            params_model=RunSavedSearchParams,
        )
        return maybe_format_markdown(result, output_format)

    if not read_only:

        @server.tool(
            name="create_saved_search",
            description=(
                "Create a new saved device search. Provide a name, a structured "
                "query dict carrying a `filters` list (same syntax as "
                "`advanced_device_search` — e.g. "
                '`{"filters": [{"AND": [{"scope": "SOFTWARE", "field": '
                '"pkgDisplayName", "operator": "IN", "values": ["nginx"]}]}]}`), '
                "and an optional description. The org is scoped automatically."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
        async def create_saved_search(
            name: str,
            query: dict[str, Any],
            description: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "create_saved_search")
            if cached is not None:
                return cached

            params: dict[str, Any] = {"name": name, "query": query}
            if description is not None:
                params["description"] = description
            try:
                result = await call_tool_workflow(
                    client,
                    _create_saved_search,
                    params,
                    params_model=CreateSavedSearchParams,
                )
            except BaseException:
                await release_idempotency(request_id, "create_saved_search")
                raise
            await store_idempotency(request_id, "create_saved_search", result)
            return result

        @server.tool(
            name="update_saved_search",
            description=(
                "Update an existing saved device search (partial update). "
                "Provide at least one of name, query, or description. The query "
                "dict uses the Automox Advanced Device Search API query syntax "
                "(see `advanced_device_search`)."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def update_saved_search(
            saved_search_id: str,
            name: str | None = None,
            query: dict[str, Any] | None = None,
            description: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "update_saved_search")
            if cached is not None:
                return cached

            params: dict[str, Any] = {"saved_search_id": saved_search_id}
            if name is not None:
                params["name"] = name
            if query is not None:
                params["query"] = query
            if description is not None:
                params["description"] = description
            try:
                result = await call_tool_workflow(
                    client,
                    _update_saved_search,
                    params,
                    params_model=UpdateSavedSearchParams,
                )
            except BaseException:
                await release_idempotency(request_id, "update_saved_search")
                raise
            await store_idempotency(request_id, "update_saved_search", result)
            return result

        @server.tool(
            name="delete_saved_search",
            description="Permanently delete a saved device search by ID.",
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def delete_saved_search(
            saved_search_id: str,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "delete_saved_search")
            if cached is not None:
                return cached

            try:
                result = await call_tool_workflow(
                    client,
                    _delete_saved_search,
                    {"saved_search_id": saved_search_id},
                    params_model=DeleteSavedSearchParams,
                )
            except BaseException:
                await release_idempotency(request_id, "delete_saved_search")
                raise
            await store_idempotency(request_id, "delete_saved_search", result)
            return result

        @server.tool(
            name="assign_policies_to_saved_search",
            description=(
                "Bulk-assign one or more policies to the result set of a "
                "saved device search. Takes the saved-search UUID and a "
                "list of policy IDs."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def assign_policies_to_saved_search(
            saved_search_uuid: str,
            policy_ids: list[int],
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "assign_policies_to_saved_search")
            if cached is not None:
                return cached

            try:
                result = await call_tool_workflow(
                    client,
                    _assign_policies_to_saved_search,
                    {
                        "saved_search_uuid": saved_search_uuid,
                        "policy_ids": policy_ids,
                    },
                    params_model=AssignPoliciesToSavedSearchParams,
                )
            except BaseException:
                await release_idempotency(request_id, "assign_policies_to_saved_search")
                raise
            await store_idempotency(request_id, "assign_policies_to_saved_search", result)
            return result

        @server.tool(
            name="refresh_saved_search_cache",
            description=(
                "Force a re-cache of a saved device search's results when they may "
                "be stale. Triggers server-side recomputation; returns once queued."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def refresh_saved_search_cache(
            search_id: str,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "refresh_saved_search_cache")
            if cached is not None:
                return cached

            try:
                result = await call_tool_workflow(
                    client,
                    _refresh_saved_search_cache,
                    {"search_id": search_id},
                    params_model=RefreshSearchCacheParams,
                )
            except BaseException:
                await release_idempotency(request_id, "refresh_saved_search_cache")
                raise
            await store_idempotency(request_id, "refresh_saved_search_cache", result)
            return result


__all__ = ["register"]

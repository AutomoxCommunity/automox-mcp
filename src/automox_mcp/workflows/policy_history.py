"""Policy History v2 workflows for Automox MCP."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from ..client import AutomoxClient
from ..utils import resolve_org_uuid
from ..utils.response import build_pagination_metadata
from ..utils.response import extract_list as _extract_list

# Legend for the `banner_stats` block the policy-report-api returns alongside
# a policy's runs. `policy_success_rate` is a PERCENTAGE (0–100), not a 0–1
# fraction — live-verified 2026-06-05 (observed values 0.0 / 60.0 / 100.0,
# e.g. 60.0 = 60%). The two companion
# fields are plain counts. Surfaced in metadata.field_notes so a model does not
# misread the value as a count or a fraction.
_BANNER_STATS_FIELD_NOTES: dict[str, str] = {
    "banner_stats.policy_success_rate": (
        "Percentage in the 0–100 range, NOT a 0–1 fraction (live-verified "
        "2026-06-05; observed values 0.0 / 60.0 / 100.0, i.e. 60.0 means 60%). "
        "Do not multiply by 100."
    ),
    "banner_stats.total_policies_applied": (
        "Count of policy applications in the window (an integer count, not a rate)."
    ),
    "banner_stats.total_successful_devices": (
        "Count of devices with a successful outcome (an integer count, not a rate)."
    ),
}


def _summarize_run(run: Mapping[str, Any]) -> dict[str, Any]:
    """Extract key fields from a policy run record.

    The policy-report-api returns snake_case JSON via @JsonNaming(SnakeCaseStrategy).
    Fields: policy_uuid, policy_id, org_uuid, policy_name, policy_type,
    policy_deleted_at, pending, success, remediation_not_applicable, failed,
    not_included, run_time, execution_token, run_count, device_count,
    blocked (v2 only).

    ``pending``/``success``/``failed``/etc. are DEVICE COUNTS per outcome for
    the run (live-verified 2026-06-05), not run statuses — emitted under
    ``device_outcomes`` so bare keys like ``success: 13`` can't be misread.
    """
    entry: dict[str, Any] = {}
    for key in (
        "policy_uuid",
        "policy_id",
        "org_uuid",
        "policy_name",
        "policy_type",
        "policy_deleted_at",
        "run_time",
        "execution_token",
        "run_count",
        "device_count",
    ):
        val = run.get(key)
        if val is not None:
            entry[key] = val

    outcomes: dict[str, Any] = {}
    for key in (
        "pending",
        "success",
        "failed",
        "not_included",
        "remediation_not_applicable",
        "blocked",
    ):
        val = run.get(key)
        if val is not None:
            outcomes[key] = val
    if outcomes:
        entry["device_outcomes"] = outcomes
    return entry


def _summarize_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Extract key fields from a policy info record.

    The policy-report-api PolicyInfoResource returns snake_case JSON:
    uuid, id, org_uuid, name, type, deleted_at, updated_at, last_run_time.
    """
    entry: dict[str, Any] = {}
    for key in (
        "uuid",
        "id",
        "org_uuid",
        "name",
        "type",
        "deleted_at",
        "updated_at",
        "last_run_time",
    ):
        val = policy.get(key)
        if val is not None:
            entry[key] = val
    return entry


# Max upstream window to fetch when a client-side filter is active. The
# policy-report-api list endpoint silently ignores filter query params,
# so we fetch a large window and filter locally. Matches the schema cap
# on `limit` (PolicyRunsV2Params.limit le=5000).
_FILTER_POOL_LIMIT = 5000

# Map result_status aliases to the counter key on a run record. Each run
# aggregates per-device outcomes; we treat the filter as "include runs
# where this counter is non-zero" since the aggregated record has no
# single-status field.
_RESULT_STATUS_KEYS = {
    "success": "success",
    "successful": "success",
    "failed": "failed",
    "failure": "failed",
    "pending": "pending",
    "not_included": "not_included",
    "remediation_not_applicable": "remediation_not_applicable",
    "blocked": "blocked",
}


async def list_policy_runs_v2(
    client: AutomoxClient,
    *,
    org_id: int,
    org_uuid: str | UUID | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    policy_name: str | None = None,
    policy_uuid: str | None = None,
    policy_type: str | None = None,
    result_status: str | None = None,
    sort: str | None = None,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List policy runs with optional filtering and time-range queries.

    The upstream policy-report-api list endpoint silently ignores filter
    query parameters (verified live against `/policy-history/policy-runs`:
    `policy_name`, `policy_type`, `policy_uuid`, `start_time`, `end_time`,
    `result_status` all return identical unfiltered results regardless of
    parameter casing). When any filter is set we fetch a large window
    upstream and apply filters + pagination client-side.
    """
    resolved_uuid = await resolve_org_uuid(
        client,
        explicit_uuid=org_uuid,
        org_id=org_id,
    )

    has_client_filter = bool(
        policy_name or policy_uuid or policy_type or start_time or end_time or result_status
    )

    params: dict[str, Any] = {"org": resolved_uuid}
    if sort:
        params["sort"] = sort
    if has_client_filter:
        params["limit"] = _FILTER_POOL_LIMIT
    else:
        if page is not None:
            params["page"] = page
        if limit is not None:
            params["limit"] = limit

    response = await client.get(
        "/policy-history/policy-runs",
        params=params,
    )

    runs = _extract_list(response)
    fetched_total = len(runs)

    metadata: dict[str, Any] = {"deprecated_endpoint": False}

    if has_client_filter:
        policy_uuid_str = str(policy_uuid) if policy_uuid else None
        policy_type_lower = policy_type.lower() if policy_type else None
        policy_name_lower = policy_name.lower() if policy_name else None
        status_key = _RESULT_STATUS_KEYS.get(result_status.lower()) if result_status else None

        def _match(run: Mapping[str, Any]) -> bool:
            if policy_uuid_str and str(run.get("policy_uuid") or "") != policy_uuid_str:
                return False
            if policy_type_lower and (
                str(run.get("policy_type") or "").lower() != policy_type_lower
            ):
                return False
            if policy_name_lower and (
                policy_name_lower not in str(run.get("policy_name") or "").lower()
            ):
                return False
            run_time = str(run.get("run_time") or "")
            if start_time and run_time < start_time:
                return False
            if end_time and run_time > end_time:
                return False
            if status_key is not None:
                counter = run.get(status_key)
                if not isinstance(counter, (int, float)) or counter <= 0:
                    return False
            return True

        filtered_runs = [r for r in runs if isinstance(r, Mapping) and _match(r)]
        filtered_total = len(filtered_runs)

        effective_limit = limit if limit is not None else 50
        effective_page = page if page is not None else 0
        start_idx = effective_page * effective_limit
        page_slice = filtered_runs[start_idx : start_idx + effective_limit]
        has_more = (start_idx + effective_limit) < filtered_total

        filters_applied = {
            k: v
            for k, v in {
                "policy_name": policy_name,
                "policy_uuid": policy_uuid_str,
                "policy_type": policy_type,
                "start_time": start_time,
                "end_time": end_time,
                "result_status": result_status,
            }.items()
            if v is not None
        }

        metadata["filter_strategy"] = "client_side"
        metadata["filter_strategy_note"] = (
            "The Automox policy-report-api list endpoint silently ignores filter "
            "query parameters. Filters and pagination are applied client-side "
            "after fetching the maximum upstream window."
        )
        metadata["filters_applied"] = filters_applied
        metadata["upstream_pool_size"] = fetched_total
        metadata["filtered_count"] = filtered_total
        next_page = effective_page + 1 if has_more else None
        metadata["pagination"] = build_pagination_metadata(
            page=effective_page,
            page_size=effective_limit,
            total_elements=filtered_total,
            has_more=has_more,
            # Legacy aliases retained for backwards-compat (#52). `next_page`
            # matches the hint policy_catalog already provides so the LLM
            # doesn't have to derive it from current_page + 1 (#76).
            extra={
                "limit": effective_limit,
                "total_count": filtered_total,
                "next_page": next_page,
            },
        )
        # Top-level suggested_next_call mirrors policy_catalog's contract
        # (#76): when more pages are available, hand the LLM the exact next
        # invocation rather than making it infer args from raw counters.
        if has_more:
            metadata["suggested_next_call"] = {
                "tool": "policy_runs_v2",
                "args": {
                    k: v
                    for k, v in {
                        "policy_uuid": policy_uuid_str or policy_uuid,
                        "policy_name": policy_name,
                        "policy_type": policy_type,
                        "start_time": start_time,
                        "end_time": end_time,
                        "result_status": result_status,
                        "sort": sort,
                        "page": next_page,
                        "limit": effective_limit,
                    }.items()
                    if v is not None
                },
            }
        if fetched_total >= _FILTER_POOL_LIMIT:
            metadata["upstream_pool_capped"] = True
            metadata["pool_cap_note"] = (
                f"Upstream returned {_FILTER_POOL_LIMIT} runs (max). If your tenant "
                "has more, older runs may be excluded from the filter pool."
            )

        summaries = [_summarize_run(r) for r in page_slice]
    else:
        summaries = [_summarize_run(r) for r in runs]

    return {
        "data": {
            "org_uuid": resolved_uuid,
            "total_runs": len(summaries),
            "runs": summaries,
        },
        "metadata": metadata,
    }


async def policy_run_count(
    client: AutomoxClient,
    *,
    org_id: int,
    org_uuid: str | UUID | None = None,
    days: int | None = None,
) -> dict[str, Any]:
    """Get aggregate policy run counts."""
    resolved_uuid = await resolve_org_uuid(
        client,
        explicit_uuid=org_uuid,
        org_id=org_id,
    )

    params: dict[str, Any] = {"org": resolved_uuid}
    if days is not None:
        params["days"] = days

    response = await client.get(
        "/policy-history/policy-run-count",
        params=params,
    )

    if isinstance(response, Mapping):
        data = dict(response)
    else:
        data = {"count": response}
    data["org_uuid"] = resolved_uuid

    return {
        "data": data,
        "metadata": {"deprecated_endpoint": False},
    }


async def policy_runs_by_policy(
    client: AutomoxClient,
    *,
    org_id: int,
    org_uuid: str | UUID | None = None,
) -> dict[str, Any]:
    """Get policy runs grouped by policy for cross-policy comparison."""
    resolved_uuid = await resolve_org_uuid(
        client,
        explicit_uuid=org_uuid,
        org_id=org_id,
    )

    response = await client.get(
        "/policy-history/policy-runs/grouped-by/policy",
        params={"org": resolved_uuid},
    )

    groups = _extract_list(response)

    return {
        "data": {
            "org_uuid": resolved_uuid,
            "total_policies": len(groups),
            "policy_groups": groups,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def get_policy_history_detail(
    client: AutomoxClient,
    *,
    org_id: int,
    policy_uuid: str,
    org_uuid: str | UUID | None = None,
    recent_runs_limit: int = 25,
) -> dict[str, Any]:
    """Get policy history details by UUID, plus recent run history.

    Earlier revisions returned only the top-level policy metadata
    (uuid, name, type, last_run_time, ...) despite the tool description
    promising "run history and status." This implementation now fetches
    `/policy-history/policy-runs/{policy_uuid}` concurrently with the
    detail endpoint and merges a summarized run list and banner_stats
    into the response. Bug #4b from issue #43.
    """
    resolved_uuid = await resolve_org_uuid(
        client,
        explicit_uuid=org_uuid,
        org_id=org_id,
    )

    detail_task = client.get(
        f"/policy-history/policies/{policy_uuid}",
        params={"org": resolved_uuid},
    )
    runs_task = client.get(
        f"/policy-history/policy-runs/{policy_uuid}",
        params={"org": resolved_uuid},
    )

    detail_response, runs_response = await asyncio.gather(
        detail_task, runs_task, return_exceptions=True
    )

    if isinstance(detail_response, BaseException):
        # The detail endpoint is the primary source — re-raise its error.
        raise detail_response

    if isinstance(detail_response, Mapping):
        detail = _summarize_policy(detail_response)
    else:
        detail = {}

    runs: list[dict[str, Any]] = []
    banner_stats: dict[str, Any] = {}
    runs_error: str | None = None
    if isinstance(runs_response, asyncio.CancelledError):
        raise runs_response
    if isinstance(runs_response, BaseException) and not isinstance(runs_response, Exception):
        # KeyboardInterrupt / SystemExit — propagate, do not swallow.
        raise runs_response
    if isinstance(runs_response, Exception):
        # The runs sub-call is best-effort; preserve detail even when it fails.
        runs_error = f"{type(runs_response).__name__}: {runs_response}"
    elif isinstance(runs_response, Mapping):
        data_block = runs_response.get("data")
        if isinstance(data_block, Mapping):
            raw_runs = data_block.get("runs") or []
            banner_stats = (
                dict(data_block.get("banner_stats") or {})
                if isinstance(data_block.get("banner_stats"), Mapping)
                else {}
            )
        elif isinstance(data_block, list):
            raw_runs = data_block
            banner_stats = {}
        else:
            raw_runs = []
            banner_stats = {}
        runs = [_summarize_run(r) for r in raw_runs if isinstance(r, Mapping) and r]

    if recent_runs_limit and recent_runs_limit > 0:
        recent_runs = runs[:recent_runs_limit]
    else:
        recent_runs = runs

    data: dict[str, Any] = dict(detail)
    data["recent_runs"] = recent_runs
    data["total_runs_returned"] = len(runs)
    if banner_stats:
        data["banner_stats"] = banner_stats

    metadata: dict[str, Any] = {"deprecated_endpoint": False}
    if banner_stats:
        # policy_success_rate is a percent (0–100), not a fraction; the
        # companions are counts. Annotate so the model reads units right.
        metadata["field_notes"] = dict(_BANNER_STATS_FIELD_NOTES)
    if runs_error:
        metadata["runs_fetch_error"] = runs_error

    return {
        "data": data,
        "metadata": metadata,
    }


async def get_policy_runs_for_policy(
    client: AutomoxClient,
    *,
    org_id: int,
    policy_uuid: str,
    org_uuid: str | UUID | None = None,
    report_days: int | None = None,
    sort: str | None = None,
    summary_only: bool = False,
) -> dict[str, Any]:
    """Get execution runs for a specific policy by UUID.

    When ``summary_only`` is true, each run is projected down to
    ``{policy_uuid, run_time, execution_token, run_count}`` and ``banner_stats`` is
    omitted — a token-efficient way to enumerate execution tokens for a policy
    with many runs.
    """
    resolved_uuid = await resolve_org_uuid(
        client,
        explicit_uuid=org_uuid,
        org_id=org_id,
    )

    params: dict[str, Any] = {"org": resolved_uuid}
    if report_days is not None:
        params["report_days"] = report_days
    if sort:
        params["sort"] = sort

    # The correct endpoint for runs-with-stats is /policy-runs/{policyUuid}
    # (not /policies/{policyUuid}/runs which returns only execution tokens).
    # Response shape: { data: { runs: [...], banner_stats: {...} }, metadata: {...} }
    response = await client.get(
        f"/policy-history/policy-runs/{policy_uuid}",
        params=params,
    )

    # Extract runs from the nested response structure
    if isinstance(response, Mapping) and "data" in response:
        data_block = response["data"]
        raw_runs = data_block.get("runs", []) if isinstance(data_block, Mapping) else []
        banner_stats = data_block.get("banner_stats", {}) if isinstance(data_block, Mapping) else {}
        metadata = response.get("metadata", {})
    else:
        raw_runs = _extract_list(response)
        banner_stats = {}
        metadata = {}

    summaries = [_summarize_run(r) for r in raw_runs]

    if summary_only:
        lean_keys = ("policy_uuid", "run_time", "execution_token", "run_count")
        summaries = [{k: run[k] for k in lean_keys if k in run} for run in summaries]
        data: dict[str, Any] = {
            "org_uuid": resolved_uuid,
            "policy_uuid": policy_uuid,
            "total_runs": len(summaries),
            "runs": summaries,
        }
    else:
        data = {
            "org_uuid": resolved_uuid,
            "policy_uuid": policy_uuid,
            "total_runs": len(summaries),
            "runs": summaries,
            "banner_stats": banner_stats,
        }

    out_metadata: dict[str, Any] = dict(metadata) if isinstance(metadata, Mapping) else {}
    if not summary_only and banner_stats:
        # policy_success_rate is a percent (0–100), not a fraction; the
        # companions are counts. Annotate so the model reads units right.
        existing_notes = out_metadata.get("field_notes")
        merged_notes = dict(existing_notes) if isinstance(existing_notes, Mapping) else {}
        merged_notes.update(_BANNER_STATS_FIELD_NOTES)
        out_metadata["field_notes"] = merged_notes

    return {
        "data": data,
        "metadata": out_metadata,
    }


async def list_policy_execution_counts(
    client: AutomoxClient,
    *,
    org_id: int,
    org_uuid: str | UUID | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    """Fleet-wide policy execution counts over a time window.

    Wraps ``GET /policy-history/policies`` (the policy index): one row per policy
    with its run count in the window, in a single round-trip. Distinct from
    ``policy_run_count`` (a single aggregate) and ``policy_runs_for_policy``
    (per-run records for one policy).
    """
    resolved_uuid = await resolve_org_uuid(
        client,
        explicit_uuid=org_uuid,
        org_id=org_id,
    )

    params: dict[str, Any] = {"org": resolved_uuid}
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time

    response = await client.get("/policy-history/policies", params=params)

    # Response shape: { data: [ {org_uuid, policy_id, policy_name, policy_uuid,
    # exec_time, run_count}, ... ] }
    if isinstance(response, Mapping):
        rows = response.get("data", [])
        metadata = response.get("metadata", {})
    else:
        rows = _extract_list(response)
        metadata = {}

    policies = [dict(row) for row in rows if isinstance(row, Mapping)]

    return {
        "data": {
            "org_uuid": resolved_uuid,
            "start_time": start_time,
            "end_time": end_time,
            "total_policies": len(policies),
            "policies": policies,
        },
        "metadata": metadata if isinstance(metadata, Mapping) else {},
    }


async def get_policy_run_detail_v2(
    client: AutomoxClient,
    *,
    org_id: int,
    policy_uuid: str,
    exec_token: str,
    org_uuid: str | UUID | None = None,
    sort: str | None = None,
    result_status: str | None = None,
    device_name: str | None = None,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Get detailed results for a specific policy run by UUID and exec token."""
    resolved_uuid = await resolve_org_uuid(
        client,
        explicit_uuid=org_uuid,
        org_id=org_id,
    )

    # The policy-report-api requires the org UUID as a query param; the JWT
    # is not used to resolve org context for this endpoint despite a sibling
    # comment in earlier revisions. Without this param the API rejects the
    # request with `Invalid or missing org from query parameters org=null`.
    # Filter params use snake_case names per the policy-report-api.
    params: dict[str, Any] = {"org": resolved_uuid}
    if sort:
        params["sort"] = sort
    if result_status:
        params["result_status"] = result_status
    if device_name:
        params["device_name"] = device_name
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit

    response = await client.get(
        f"/policy-history/policies/{policy_uuid}/{exec_token}",
        params=params,
    )

    results = _extract_list(response)

    return {
        "data": {
            "org_uuid": resolved_uuid,
            "policy_uuid": policy_uuid,
            "exec_token": exec_token,
            "total_results": len(results),
            "results": results,
        },
        "metadata": {
            "deprecated_endpoint": False,
            # Live-verified 2026-06-05 — without this legend the model has to
            # guess what a large negative exit_code means.
            "field_notes": {
                "exit_code": (
                    "Raw process exit code from the policy script on the device: "
                    "0 = success; negative values on Windows are NTSTATUS codes "
                    "as signed 32-bit ints (e.g. -1073741502 = 0xC0000142 "
                    "STATUS_DLL_INIT_FAILED)."
                ),
                "result_status": "Lowercase per-device outcome string (e.g. success, failed).",
            },
        },
    }

"""Policy workflows for Automox MCP."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

import httpx

from ..client import AutomoxAPIError, AutomoxClient, AutomoxResponse
from ..utils import resolve_org_uuid
from ..utils.response import normalize_status as _normalize_status
from ..utils.response import require_org_id

logger = logging.getLogger(__name__)

# Safety cap on auto-pagination to prevent runaway loops.
_MAX_PAGINATION_PAGES = 50


def _take(sequence: Sequence[Any], limit: int) -> Sequence[Any]:
    """Take first N items from a sequence."""
    if limit <= 0:
        return []
    return sequence[:limit]


async def summarize_policy_activity(
    client: AutomoxClient,
    *,
    org_uuid: UUID,
    window_days: int = 7,
    top_failures: int = 5,
    max_runs: int = 200,
) -> dict[str, Any]:
    """Aggregate policy activity for an organization over the requested window."""

    # Get policy run counts — this endpoint may not be available on all API
    # configurations, so treat it as optional.
    run_counts: AutomoxResponse = {}
    try:
        count_params = {"org": str(org_uuid), "days": window_days}
        run_counts = await client.get(
            "/policy-history/policy-run-count",
            params=count_params,
        )
    except AutomoxAPIError:
        logger.warning("policy-run-count endpoint unavailable, skipping")

    # Get policy runs — use only org (required) + limit to avoid validation errors.
    # The sort default is already "run_time:desc" per the API spec.
    run_params: dict[str, Any] = {
        "org": str(org_uuid),
        "limit": min(max_runs, 5000),
    }
    policy_runs = await client.get(
        "/policy-history/policy-runs",
        params=run_params,
    )

    runs: Sequence[Mapping[str, Any]] = []
    if isinstance(policy_runs, Mapping):
        run_items = policy_runs.get("data")
        if isinstance(run_items, Sequence):
            runs = run_items
    elif isinstance(policy_runs, Sequence):
        runs = policy_runs

    # Each run item contains aggregate device counts: success, failed, pending,
    # not_included, remediation_not_applicable, device_count, etc.
    status_counter: Counter[str] = Counter()
    policy_breakdown: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total_runs": 0, "failed_runs": 0, "total_devices": 0, "failed_devices": 0}
    )

    for item in runs:
        failed = item.get("failed") or 0
        success = item.get("success") or 0
        device_count = item.get("device_count") or 0

        # Classify the run overall
        if failed > 0:
            status_counter["failed"] += 1
        elif success > 0:
            status_counter["success"] += 1
        else:
            status_counter["unknown"] += 1

        policy_key = str(
            item.get("policy_uuid") or item.get("policy_id") or item.get("policy_name") or "unknown"
        )
        entry = policy_breakdown[policy_key]
        entry["policy_uuid"] = item.get("policy_uuid") or entry.get("policy_uuid")
        entry["policy_name"] = item.get("policy_name") or entry.get("policy_name") or policy_key
        entry["policy_type"] = item.get("policy_type") or entry.get("policy_type")
        entry["total_runs"] += 1
        entry["total_devices"] += device_count
        entry["failed_devices"] += failed
        if failed > 0:
            entry["failed_runs"] += 1

    top_failures_list = sorted(
        (
            {
                "policy_uuid": entry.get("policy_uuid"),
                "policy_name": entry.get("policy_name"),
                "failed_runs": entry["failed_runs"],
                "total_runs": entry["total_runs"],
                "failure_rate": entry["failed_runs"] / entry["total_runs"]
                if entry["total_runs"]
                else 0.0,
            }
            for entry in policy_breakdown.values()
            if entry["failed_runs"] > 0
        ),
        key=lambda item: (item["failure_rate"], item["failed_runs"]),
        reverse=True,
    )[:top_failures]

    # PolicyRunCount returns {"policy_runs": N} directly
    total_policy_runs = None
    if isinstance(run_counts, Mapping):
        total_policy_runs = run_counts.get("policy_runs")

    overview = {
        "window_days": window_days,
        "total_policy_runs": total_policy_runs,
        "total_runs_considered": len(runs),
        "status_breakdown": dict(status_counter),
        "top_failing_policies": top_failures_list,
    }

    metadata = {
        "deprecated_endpoint": False,
        "org_uuid": str(org_uuid),
        "window_days": window_days,
        "total_runs_considered": len(runs),
    }

    return {
        "data": overview,
        "metadata": metadata,
    }


async def summarize_policy_execution_history(
    client: AutomoxClient,
    *,
    org_uuid: UUID,
    policy_uuid: UUID,
    report_days: int | None = 7,
    limit: int = 50,
) -> dict[str, Any]:
    """Return a concise execution timeline for a specific policy.

    Uses ``/policy-history/policy-runs`` with a ``policy_uuid`` filter
    which returns rich per-run data (device counts, success/failure
    breakdowns) instead of the minimal ``/policies/{uuid}/runs`` endpoint.
    """

    # The API requires operator syntax for filters (e.g. policy_uuid:equals=UUID).
    # httpx URL-encodes colons in param keys (%3A), which the API rejects.
    # Build the full query string manually to preserve the literal colon.
    from urllib.parse import urlencode

    safe_params = urlencode({"org": str(org_uuid), "limit": min(limit, 5000)})
    path = f"/policy-history/policy-runs?policy_uuid:equals={policy_uuid}&{safe_params}"
    payload = await client.get(path)

    runs: Sequence[Mapping[str, Any]] = []
    policy_name: Any = None

    if isinstance(payload, Mapping):
        run_items = payload.get("data")
        if isinstance(run_items, Sequence):
            runs = run_items
        # Try to extract policy name from first run item
        if runs:
            policy_name = runs[0].get("policy_name")
    elif isinstance(payload, Sequence):
        runs = payload  # type: ignore[assignment]

    runs = list(_take(runs, limit))

    status_counter: Counter[str] = Counter()
    timeline = []

    for item in runs:
        exec_token = item.get("execution_token") or item.get("exec_token")
        run_time = item.get("run_time")
        failed = item.get("failed") or 0
        success = item.get("success") or 0

        if failed > 0:
            status = "failed"
        elif success > 0:
            status = "success"
        else:
            status = "unknown"
        status_counter[status] += 1

        timeline.append(
            {
                "exec_token": exec_token,
                "run_time": run_time,
                "status": status if status != "unknown" else None,
                "device_count": item.get("device_count"),
                "success": success,
                "failed": failed,
                "pending": item.get("pending"),
                "not_included": item.get("not_included"),
            }
        )

    data = {
        "policy_uuid": str(policy_uuid),
        "policy_name": policy_name,
        "report_days": report_days,
        "status_breakdown": dict(status_counter),
        "recent_executions": timeline,
    }

    metadata: dict[str, Any] = {
        "deprecated_endpoint": False,
        "org_uuid": str(org_uuid),
        "policy_uuid": str(policy_uuid),
        "report_days": report_days,
        "run_count": len(timeline),
    }

    return {
        "data": data,
        "metadata": metadata,
    }


async def summarize_policies(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    limit: int = 20,
    page: int | None = 0,
    include_inactive: bool = False,
) -> dict[str, Any]:
    """Provide a curated view of Automox policies."""

    resolved_org_id = require_org_id(client, org_id)

    params = {"o": resolved_org_id}
    if limit is not None:
        params["limit"] = limit
    if page is not None:
        params["page"] = page

    policies: list[Mapping[str, Any]] = []
    current_page = page or 0
    accumulated = 0
    type_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    filtered: list[Mapping[str, Any]] = []
    preview: list[Mapping[str, Any]] = []

    for _page_num in range(_MAX_PAGINATION_PAGES):
        policies_response = await client.get("/policies", params=params)
        page_results: list[Mapping[str, Any]] = []
        if isinstance(policies_response, Sequence):
            page_results = [item for item in policies_response if isinstance(item, Mapping)]

        policies.extend(page_results)
        accumulated += len(page_results)

        for policy_item in page_results:
            if not isinstance(policy_item, Mapping):
                continue
            status_raw = str(policy_item.get("status") or "").lower()
            active_flag = policy_item.get("active")
            if active_flag is None:
                active_flag = policy_item.get("enabled")
            if active_flag is None:
                active_flag = policy_item.get("is_active")
            if active_flag is not None:
                is_active = active_flag not in (False, 0, "false", "inactive")
            else:
                is_active = status_raw not in ("inactive", "disabled")
            if not include_inactive and not is_active:
                continue

            policy_type = (
                policy_item.get("policy_type_name")
                or policy_item.get("policy_type")
                or policy_item.get("type")
                or "unknown"
            ).lower()
            if policy_type == "custom":
                policy_type = "worklet"
            type_counts[policy_type] += 1
            status = _normalize_status(
                policy_item.get("status") or ("active" if is_active else "inactive")
            )
            status_counts[status] += 1

            filtered.append(policy_item)

            if limit is None or len(preview) < limit:
                preview.append(
                    {
                        "policy_id": policy_item.get("id"),
                        "policy_uuid": policy_item.get("guid") or policy_item.get("uuid"),
                        "name": policy_item.get("name"),
                        "type": policy_type,
                        "status": policy_item.get("status"),
                        "targets": policy_item.get("target"),
                        "server_groups": policy_item.get("server_groups"),
                        "schedule_days": policy_item.get("schedule_days"),
                        "schedule_time": policy_item.get("schedule_time"),
                        "next_run": policy_item.get("next_run"),
                    }
                )

        has_reached_preview_cap = limit is not None and len(preview) >= limit
        next_page_index = current_page + 1
        params["page"] = next_page_index
        current_page = next_page_index

        if has_reached_preview_cap or not page_results:
            break

    stats_params = {"o": resolved_org_id}
    stats_data = await client.get("/policystats", params=stats_params)
    total_available: int | None = None
    if isinstance(stats_data, Sequence):
        # Count unique policies represented in the stats payload as a proxy for total policies
        policy_ids = {
            item.get("policy_id")
            for item in stats_data
            if isinstance(item, Mapping) and item.get("policy_id") is not None
        }
        if policy_ids:
            total_available = len(policy_ids)
        else:
            total_available = len([item for item in stats_data if isinstance(item, Mapping)])

    returned_count_raw = len(policies)
    returned_count = len(preview)
    normalized_page = page if page is None else max(page, 0)
    if total_available is not None and limit is not None and normalized_page is not None:
        has_more = (normalized_page + 1) * limit < total_available
    elif normalized_page is None:
        # Auto-pagination already fetched everything; no more data
        has_more = total_available is not None and returned_count_raw < total_available
    else:
        has_more = bool(limit is not None and returned_count_raw >= limit)
    next_page: int | None = None
    if has_more and normalized_page is not None:
        next_page = normalized_page + 1
    previous_page: int | None = None
    if normalized_page is not None and normalized_page > 0:
        previous_page = normalized_page - 1

    pagination: dict[str, Any] = {
        "page": normalized_page,
        "current_page": normalized_page,
        "limit": limit,
        "returned_count": returned_count,
        "returned_count_raw": returned_count_raw,
        "has_more": bool(has_more),
        "next_page": next_page,
        "previous_page": previous_page,
    }
    if total_available is not None:
        pagination["total_count"] = total_available
    pagination["filtered_count"] = len(filtered)

    suggested_next_call: dict[str, Any] | None = None
    if has_more and normalized_page is not None:
        suggested_next_call = {
            "tool": "policy_catalog",
            "args": {
                "page": normalized_page + 1,
                "limit": limit,
                "include_inactive": include_inactive,
            },
        }

    data = {
        "total_policies_considered": len(filtered),
        "policies_returned": len(preview),
        "policy_type_breakdown": dict(type_counts),
        "status_breakdown": dict(status_counts),
        "policies": preview,
        "policy_stats": stats_data,
    }
    if total_available is not None:
        data["total_policies_available"] = total_available

    metadata: dict[str, Any] = {
        "deprecated_endpoint": False,
        "org_id": resolved_org_id,
        "requested_limit": limit,
        "requested_page": normalized_page,
        "include_inactive": include_inactive,
        "current_page": normalized_page,
        "limit": limit,
        "pagination": pagination,
    }
    if total_available is not None:
        metadata["total_policies_available"] = total_available
    if suggested_next_call:
        metadata["suggested_next_call"] = suggested_next_call
    if has_more:
        note = (
            f"{returned_count} of {total_available} policies returned; follow "
            f"metadata.suggested_next_call or increment page to continue pagination."
            if total_available is not None
            else "Partial results returned; follow metadata.suggested_next_call or "
            "increment page to continue pagination."
        )
        metadata["notes"] = [note]

    return {
        "data": data,
        "metadata": metadata,
    }


def _decode_schedule_days_bitmask(bitmask: int) -> dict[str, Any]:
    """Decode a schedule_days bitmask into human-readable format.

    Automox uses an 8-bit pattern with a trailing zero at bit 0.
    Bit positions: 7=Sun, 6=Sat, 5=Fri, 4=Thu, 3=Wed, 2=Tue, 1=Mon, 0=unused
    """
    if not bitmask or bitmask == 0:
        return {"interpretation": "Unscheduled (no days selected)"}

    # Map bitmask to day names using Automox's bit positions
    days_map = {
        128: "Sunday",
        64: "Saturday",
        32: "Friday",
        16: "Thursday",
        8: "Wednesday",
        4: "Tuesday",
        2: "Monday",
    }

    selected_days = []
    for bit, day_name in days_map.items():
        if bitmask & bit:
            selected_days.append(day_name)

    # Detect common patterns
    interpretation = None
    if bitmask == 62:  # Mon-Fri (2+4+8+16+32)
        interpretation = "Weekdays (Monday through Friday)"
    elif bitmask == 192:  # Sat+Sun (64+128)
        interpretation = "Weekend (Saturday and Sunday)"
    elif bitmask == 254:  # All days (2+4+8+16+32+64+128)
        interpretation = "Every day (all 7 days)"
    else:
        interpretation = f"{len(selected_days)} days: {', '.join(selected_days)}"

    return {
        "bitmask_value": bitmask,
        "interpretation": interpretation,
        "selected_days": selected_days,
        "reference": {
            "weekdays_Mon_to_Fri": 62,
            "weekend_Sat_and_Sun": 192,
            "every_day": 254,
            "note": (
                "Automox uses bit positions: 7=Sun(128), 6=Sat(64), 5=Fri(32), "
                "4=Thu(16), 3=Wed(8), 2=Tue(4), 1=Mon(2), 0=unused"
            ),
        },
    }


async def describe_policy(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    policy_id: int,
    include_recent_runs: int = 5,
) -> dict[str, Any]:
    """Return the configuration and recent history for a specific policy.

    Uses client.org_id for Console API and client.account_uuid for Policy Report API.
    """

    resolved_org_id = require_org_id(client, org_id)

    params = {"o": resolved_org_id}
    try:
        policy_response = await client.get(f"/policies/{policy_id}", params=params)
    except (AutomoxAPIError, httpx.RequestError) as e:
        raise ValueError(
            f"Failed to retrieve policy {policy_id} from organization {resolved_org_id}. "
            f"The policy may not exist in this organization, may have been deleted, "
            f"or may belong to a different org/zone. Use policy_catalog to verify."
        ) from e

    policy_data = policy_response if isinstance(policy_response, Mapping) else {}
    policy_uuid_value = (
        policy_data.get("guid") or policy_data.get("uuid") or policy_data.get("policy_uuid")
    )

    recent_activity = None
    if include_recent_runs and policy_uuid_value:
        history_org_uuid: UUID | None = None
        raw_policy_org_uuid = (
            policy_data.get("org_uuid")
            or policy_data.get("organization_uuid")
            or policy_data.get("organization_uid")
        )
        if raw_policy_org_uuid:
            try:
                history_org_uuid = UUID(str(raw_policy_org_uuid))
            except (TypeError, ValueError):
                history_org_uuid = None
        if history_org_uuid is None:
            try:
                resolved_org_uuid = await resolve_org_uuid(
                    client,
                    org_id=resolved_org_id,
                    allow_account_uuid=False,
                )
            except ValueError:
                resolved_org_uuid = None
            if resolved_org_uuid:
                try:
                    history_org_uuid = UUID(resolved_org_uuid)
                except (TypeError, ValueError):
                    history_org_uuid = None

        if history_org_uuid is not None:
            try:
                policy_uuid = UUID(str(policy_uuid_value))
                history = await summarize_policy_execution_history(
                    client,
                    org_uuid=history_org_uuid,
                    policy_uuid=policy_uuid,
                    report_days=30,
                    limit=include_recent_runs,
                )
                recent_activity = {
                    "status_breakdown": history["data"].get("status_breakdown"),
                    "recent_executions": history["data"].get("recent_executions"),
                }
            except (AutomoxAPIError, ValueError, TypeError, KeyError) as exc:
                # Gracefully handle if policy history is unavailable
                logger.debug("Failed to fetch policy history: %s", exc)
                recent_activity = None

    # Decode schedule_days bitmask for better readability and add to top level
    schedule_interpretation = None
    schedule_days = policy_data.get("schedule_days")
    if schedule_days is not None:
        schedule_interpretation = _decode_schedule_days_bitmask(schedule_days)

    data = {
        "policy": policy_data,
        "recent_activity": recent_activity,
    }

    # Add schedule interpretation at top level for prominence
    if schedule_interpretation:
        data["schedule_interpretation"] = schedule_interpretation
        data["_important"] = {
            "current_schedule": schedule_interpretation["interpretation"],
            "schedule_days_bitmask": schedule_days,
            "schedule_time": policy_data.get("schedule_time"),
            "note": (
                "Use resource://policies/schedule-syntax for scheduling help. "
                "To update schedule, use {'days': ['weekend'], 'time': '02:00'} syntax."
            ),
        }

    metadata: dict[str, Any] = {
        "deprecated_endpoint": False,
        "org_id": resolved_org_id,
        "policy_id": policy_id,
        "include_recent_runs": include_recent_runs,
    }
    if policy_uuid_value:
        metadata["policy_uuid"] = str(policy_uuid_value)

    return {
        "data": data,
        "metadata": metadata,
    }


async def describe_policy_run_result(
    client: AutomoxClient,
    *,
    org_uuid: UUID,
    policy_uuid: UUID,
    exec_token: UUID,
    sort: str | None = None,
    result_status: str | None = None,
    device_name: str | None = None,
    page: int | None = None,
    limit: int | None = None,
    max_output_length: int | None = None,
) -> dict[str, Any]:
    """Retrieve per-device results for a specific policy execution."""

    params: dict[str, Any] = {"org": str(org_uuid)}
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
    if max_output_length is not None:
        params["max_output_length"] = max_output_length

    path = f"/policy-history/policies/{policy_uuid}/{exec_token}"
    payload = await client.get(path, params=params)

    devices_raw: Sequence[Mapping[str, Any]] = []
    pagination_meta: Mapping[str, Any] | None = None
    if isinstance(payload, Mapping):
        data_section = payload.get("data")
        if isinstance(data_section, Sequence):
            devices_raw = data_section  # type: ignore[assignment]
        meta_section = payload.get("metadata")
        if isinstance(meta_section, Mapping):
            pagination_meta = meta_section
    elif isinstance(payload, Sequence):
        devices_raw = payload  # type: ignore[assignment]

    status_counter: Counter[str] = Counter()
    device_results: list[dict[str, Any]] = []

    for entry in devices_raw:
        if not isinstance(entry, Mapping):
            continue
        status = _normalize_status(entry.get("result_status"))
        status_counter[status] += 1
        device_results.append(
            {
                "device_id": entry.get("device_id"),
                "device_uuid": entry.get("device_uuid"),
                "hostname": entry.get("hostname"),
                "custom_name": entry.get("custom_name"),
                "display_name": entry.get("display_name"),
                "result_status": status,
                "result_reason": entry.get("result_reason") or entry.get("result-reason"),
                "run_time": entry.get("run_time"),
                "event_time": entry.get("event_time"),
                "stdout": entry.get("stdout"),
                "stderr": entry.get("stderr"),
                "exit_code": entry.get("exit_code")
                if entry.get("exit_code") is not None
                else entry.get("error_code"),
                "patches": entry.get("patches"),
                "device_deleted_at": entry.get("device_deleted_at"),
            }
        )

    data = {
        "policy_uuid": str(policy_uuid),
        "exec_token": str(exec_token),
        "result_summary": {
            "total_devices": len(device_results),
            "status_breakdown": dict(status_counter),
        },
        "devices": device_results,
        "pagination": pagination_meta,
    }

    metadata = {
        "deprecated_endpoint": False,
        "org_uuid": str(org_uuid),
        "policy_uuid": str(policy_uuid),
        "exec_token": str(exec_token),
        "result_count": len(device_results),
        "status_breakdown": dict(status_counter),
        "page": pagination_meta.get("current_page") if pagination_meta else None,
        "limit": pagination_meta.get("limit") if pagination_meta else limit,
        "total_count": pagination_meta.get("total_count") if pagination_meta else None,
    }

    return {
        "data": data,
        "metadata": metadata,
    }


async def summarize_patch_approvals(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    status: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Summarize pending Automox patch approvals and provide decision context."""

    resolved_org_id = require_org_id(client, org_id)

    params = {"o": resolved_org_id, "limit": limit}
    approvals = await client.get("/approvals", params=params)
    approvals = approvals if isinstance(approvals, Sequence) else []

    status_filter = (status or "").lower()
    status_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    pending_items = []

    for approval_item in approvals:
        if not isinstance(approval_item, Mapping):
            continue
        approval_status = (approval_item.get("status") or "unknown").lower()
        status_counts[approval_status] += 1

        if status_filter and approval_status != status_filter:
            continue

        severity = (
            approval_item.get("severity") or approval_item.get("cvss_severity") or "unknown"
        ).lower()
        severity_counts[severity] += 1

        pending_items.append(
            {
                "approval_id": approval_item.get("id"),
                "title": approval_item.get("title") or approval_item.get("name"),
                "status": approval_item.get("status"),
                "severity": approval_item.get("severity"),
                "device_count": approval_item.get("device_count")
                or approval_item.get("devices_affected"),
                "created_at": approval_item.get("created_at"),
                "deadline": approval_item.get("deadline") or approval_item.get("expires_at"),
            }
        )

    data = {
        "total_approvals_considered": len(approvals),
        "status_breakdown": dict(status_counts),
        "severity_breakdown": dict(severity_counts),
        "approvals": pending_items[:limit],
    }

    metadata = {
        "deprecated_endpoint": False,
        "org_id": resolved_org_id,
        "status_filter": status_filter or None,
        "requested_limit": limit,
    }

    return {
        "data": data,
        "metadata": metadata,
    }


async def get_policy_compliance_stats(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
) -> dict[str, Any]:
    """Retrieve policy compliance statistics for the organization.

    Returns per-policy device counts, compliance rates, and status breakdowns
    from the /policystats endpoint.
    """
    resolved_org_id = require_org_id(client, org_id)

    params = {"o": resolved_org_id}
    stats = await client.get("/policystats", params=params)

    policy_stats: list[dict[str, Any]] = []
    total_compliant = 0
    total_noncompliant = 0
    total_devices = 0

    if isinstance(stats, Sequence):
        for item in stats:
            if not isinstance(item, Mapping):
                continue
            compliant = item.get("compliant", 0) or 0
            noncompliant = item.get("non_compliant", 0) or item.get("noncompliant", 0) or 0
            device_count = compliant + noncompliant

            total_compliant += compliant
            total_noncompliant += noncompliant
            total_devices += device_count

            policy_stats.append(
                {
                    "policy_id": item.get("policy_id"),
                    "policy_name": item.get("policy_name") or item.get("name"),
                    "compliant_devices": compliant,
                    "noncompliant_devices": noncompliant,
                    "total_devices": device_count,
                    "compliance_rate_percent": (
                        round(compliant / device_count * 100, 1) if device_count > 0 else 0
                    ),
                }
            )

    overall_rate = round(total_compliant / total_devices * 100, 1) if total_devices > 0 else 0

    return {
        "data": {
            "overall_compliance": {
                "total_devices_evaluated": total_devices,
                "compliant": total_compliant,
                "noncompliant": total_noncompliant,
                "compliance_rate_percent": overall_rate,
            },
            "per_policy_stats": policy_stats,
        },
        "metadata": {
            "deprecated_endpoint": False,
            "org_id": resolved_org_id,
            "policy_count": len(policy_stats),
        },
    }


__all__ = [
    "describe_policy",
    "describe_policy_run_result",
    "get_policy_compliance_stats",
    "summarize_patch_approvals",
    "summarize_policies",
    "summarize_policy_activity",
    "summarize_policy_execution_history",
]

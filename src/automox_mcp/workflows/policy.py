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
from ..utils.response import build_pagination_metadata, require_org_id
from ..utils.response import normalize_status as _normalize_status

logger = logging.getLogger(__name__)


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

        # Classify the run overall. The catch-all bucket is NOT "unknown": a run
        # with no failures and no successes means every device was pending /
        # not_included / remediation_not_applicable (benign no-op or in progress).
        if failed > 0:
            status_counter["failed"] += 1
        elif success > 0:
            status_counter["success"] += 1
        else:
            status_counter["no_success_or_failure"] += 1

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

    # PolicyRunCount returns {"policy_runs": N} directly. This counts ALL
    # runs in the last `window_days` days. The /policy-runs endpoint we
    # used above is server-capped at roughly the most-recent 100 events
    # (or last ~24 hours), regardless of `limit`, `days`, or
    # `start_time`/`end_time` parameters. So `total_policy_runs` and
    # `total_runs_considered` measure different things and may legitimately
    # disagree when the org runs more than ~100 policy runs per day.
    total_policy_runs = None
    if isinstance(run_counts, Mapping):
        total_policy_runs = run_counts.get("policy_runs")

    runs_considered = len(runs)
    sample_is_truncated = isinstance(total_policy_runs, int) and total_policy_runs > runs_considered

    overview = {
        "window_days": window_days,
        "total_policy_runs": total_policy_runs,
        "total_runs_considered": runs_considered,
        "sample_is_truncated": sample_is_truncated,
        "status_breakdown": dict(status_counter),
        "top_failing_policies": top_failures_list,
    }

    metadata: dict[str, Any] = {
        "deprecated_endpoint": False,
        "org_uuid": str(org_uuid),
        "window_days": window_days,
        "total_runs_considered": runs_considered,
        "sample_is_truncated": sample_is_truncated,
        "field_notes": {
            "status_breakdown": (
                "Counts RUNS by overall result: 'failed' = at least one device "
                "failed; 'success' = at least one device succeeded and none "
                "failed; 'no_success_or_failure' = every device was pending / "
                "not_included / remediation_not_applicable (a benign no-op or "
                "still in progress, not an error). These are run counts, not "
                "device counts."
            ),
        },
    }
    if sample_is_truncated:
        metadata["sample_note"] = (
            f"Org had {total_policy_runs} policy runs over the {window_days}-day "
            f"window, but the /policy-history/policy-runs endpoint is server-capped "
            f"at the most recent {runs_considered} events (≈last 24 hours) "
            f"regardless of limit/days/start_time params. The status_breakdown "
            f"and top_failing_policies in this response reflect that recent "
            f"sample only — they are NOT a window-wide aggregate. Use "
            f"policy_runs_for_policy with a specific policy_uuid to get full "
            f"per-policy history within the window."
        )

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
    from datetime import UTC, datetime, timedelta
    from urllib.parse import urlencode

    params_dict: dict[str, str] = {
        "org": str(org_uuid),
        "limit": str(min(limit, 5000)),
    }
    # Apply date filter when report_days is specified
    if report_days is not None and report_days > 0:
        start_date = datetime.now(UTC) - timedelta(days=report_days)
        params_dict["start_time"] = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")

    safe_params = urlencode(params_dict)
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
        pending = item.get("pending") or 0
        not_included = item.get("not_included") or 0
        remediation_not_applicable = item.get("remediation_not_applicable") or 0

        # Run-level status: failed wins, then success. The else branch is NOT
        # "unknown" — a run with no failures and no successes but nonzero
        # pending/not_included/remediation_not_applicable is a benign no-op or
        # still in progress (live-verified 2026-06-05). The conservative call is
        # status=None there (the probe verified no run-level status vocabulary),
        # with device_outcomes carrying the disambiguating counts.
        if failed > 0:
            status: str | None = "failed"
            status_counter["failed"] += 1
        elif success > 0:
            status = "success"
            status_counter["success"] += 1
        elif pending or not_included or remediation_not_applicable:
            status = None
            status_counter["no_success_or_failure"] += 1
        else:
            status = None
            status_counter["no_success_or_failure"] += 1

        # Group ALL device outcome counts under device_outcomes (device counts
        # per outcome, not run statuses), mirroring _summarize_run in
        # policy_history.py. `blocked` is included for parity with that key set;
        # it is omitted when absent (this endpoint's resource does not emit it).
        outcomes = {
            key: item.get(key)
            for key in (
                "pending",
                "success",
                "failed",
                "not_included",
                "remediation_not_applicable",
                "blocked",
            )
            if item.get(key) is not None
        }

        timeline.append(
            {
                "exec_token": exec_token,
                "run_time": run_time,
                "status": status,
                "device_count": item.get("device_count"),
                "device_outcomes": outcomes,
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
        "field_notes": {
            "device_outcomes": (
                "Device counts per outcome for the run (live-verified "
                "2026-06-05), not run statuses; they sum to device_count. A run "
                "with failed=0 and success=0 but nonzero pending/not_included/"
                "remediation_not_applicable completed as a benign no-op or is "
                "still in progress — not a failure (status is null in that case)."
            ),
        },
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
    include_stats: bool = False,
) -> dict[str, Any]:
    """Provide a curated view of Automox policies.

    Pagination is pass-through to /policies (the user's `page` and `limit`
    map 1:1 to the upstream params). A page may contain fewer than `limit`
    active policies when some entries on that page are inactive and
    `include_inactive=False`, but the cursor remains correct because each
    user-page is exactly one upstream page.

    `policy_stats` is opt-in (default off). The /policystats payload can
    consume the bulk of the response token budget and previously caused
    truncation of the `policies` array — set `include_stats=True` to
    re-enable when the per-policy compliance breakdown is needed.
    """

    resolved_org_id = require_org_id(client, org_id)

    params: dict[str, Any] = {"o": resolved_org_id}
    if limit is not None:
        params["limit"] = limit
    if page is not None:
        params["page"] = page

    policies_response = await client.get("/policies", params=params)
    page_results: list[Mapping[str, Any]] = []
    if isinstance(policies_response, Sequence):
        page_results = [item for item in policies_response if isinstance(item, Mapping)]

    type_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    filtered: list[Mapping[str, Any]] = []
    preview: list[Mapping[str, Any]] = []

    for policy_item in page_results:
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

        policy_type = str(
            policy_item.get("policy_type_name")
            or policy_item.get("policy_type")
            or policy_item.get("type")
            or "unknown"
        ).lower()
        if policy_type == "custom":
            policy_type = "worklet"
        type_counts[policy_type] += 1
        normalized = _normalize_status(
            policy_item.get("status") or ("active" if is_active else "inactive")
        )
        status_counts[normalized] += 1

        filtered.append(policy_item)
        preview_entry = {
            "policy_id": policy_item.get("id"),
            "policy_uuid": policy_item.get("guid") or policy_item.get("uuid"),
            "name": policy_item.get("name"),
            "type": policy_type,
            "status": policy_item.get("status"),
            "targets": policy_item.get("target"),
            "server_groups": policy_item.get("server_groups"),
            "schedule_days": policy_item.get("schedule_days"),
            "schedule_time": policy_item.get("schedule_time"),
            "installation_do_not_disturb_honored": policy_item.get(
                "installation_do_not_disturb_honored"
            ),
            "reboot_do_not_disturb_honored": policy_item.get("reboot_do_not_disturb_honored"),
        }
        # schedule_days is a bitmask (describe_policy already decodes it);
        # decode here too so catalog rows are self-describing.
        schedule_days = policy_item.get("schedule_days")
        if isinstance(schedule_days, int) and not isinstance(schedule_days, bool):
            preview_entry["schedule_days_decoded"] = _decode_schedule_days_bitmask(schedule_days)[
                "interpretation"
            ]
        # The old projection read `next_run`, a key the /policies list endpoint
        # never returns (confirmed absent live 2026-06-05) — it emitted a
        # confident `next_run: null` that read as "nothing scheduled" (audit
        # finding N8). The spec-defined field is `next_remediation`; surface it
        # only when present so we never confabulate a next-run timestamp.
        next_remediation = policy_item.get("next_remediation")
        if next_remediation is not None:
            preview_entry["next_remediation"] = next_remediation
        preview.append(preview_entry)

    stats_data: Any = None
    total_available: int | None = None
    if include_stats:
        stats_data = await client.get("/policystats", params={"o": resolved_org_id})
        if isinstance(stats_data, Sequence):
            policy_ids = {
                item.get("policy_id")
                for item in stats_data
                if isinstance(item, Mapping) and item.get("policy_id") is not None
            }
            if policy_ids:
                total_available = len(policy_ids)
            else:
                total_available = len([item for item in stats_data if isinstance(item, Mapping)])

    returned_count_raw = len(page_results)
    normalized_page = page if page is None else max(page, 0)

    if total_available is not None and limit is not None and normalized_page is not None:
        has_more = (normalized_page + 1) * limit < total_available
    else:
        # Without a stats-derived total, defer to the page itself: a full page
        # implies there may be more; a short page is the last page.
        has_more = bool(limit is not None and returned_count_raw >= limit)

    next_page: int | None = None
    if has_more and normalized_page is not None:
        next_page = normalized_page + 1
    previous_page: int | None = None
    if normalized_page is not None and normalized_page > 0:
        previous_page = normalized_page - 1

    pagination: dict[str, Any] = build_pagination_metadata(
        page=normalized_page,
        page_size=limit,
        total_elements=total_available,
        has_more=bool(has_more),
        # Legacy aliases retained for backwards-compat (#52).
        extra={
            "current_page": normalized_page,
            "limit": limit,
            "returned_count": len(preview),
            "returned_count_raw": returned_count_raw,
            "next_page": next_page,
            "previous_page": previous_page,
            "total_count": total_available,
            "filtered_count": len(filtered),
        },
    )

    suggested_next_call: dict[str, Any] | None = None
    if has_more and normalized_page is not None:
        suggested_next_call = {
            "tool": "policy_catalog",
            "args": {
                "page": normalized_page + 1,
                "limit": limit,
                "include_inactive": include_inactive,
                "include_stats": include_stats,
            },
        }

    data: dict[str, Any] = {
        "total_policies_considered": len(filtered),
        "policies_returned": len(preview),
        "policy_type_breakdown": dict(type_counts),
        "status_breakdown": dict(status_counts),
        "policies": preview,
    }
    if include_stats:
        data["policy_stats"] = stats_data
    if total_available is not None:
        data["total_policies_available"] = total_available

    metadata: dict[str, Any] = {
        "deprecated_endpoint": False,
        "org_id": resolved_org_id,
        "requested_limit": limit,
        "requested_page": normalized_page,
        "include_inactive": include_inactive,
        "include_stats": include_stats,
        "current_page": normalized_page,
        "limit": limit,
        "pagination": pagination,
        "field_notes": {
            "next_remediation": (
                "Spec-defined next-remediation timestamp (per spec, not "
                "observed live on this tenant 2026-06-05 — the /policies list "
                "endpoint omitted it). Surfaced only when the upstream returns "
                "a value; absence does NOT mean 'nothing scheduled' — derive "
                "the next run from schedule_days + schedule_time when needed."
            ),
        },
    }
    if total_available is not None:
        metadata["total_policies_available"] = total_available
    if suggested_next_call:
        metadata["suggested_next_call"] = suggested_next_call
    if has_more:
        if total_available is not None:
            note = (
                f"{len(preview)} of {total_available} policies returned; follow "
                f"metadata.suggested_next_call or increment page to continue pagination."
            )
        else:
            note = (
                "Page is full; more results may be available. Call again with "
                "`page=<next_page>` to continue."
            )
        metadata["notes"] = [note]
    if not include_stats:
        metadata.setdefault("notes", []).append(
            "policy_stats omitted (include_stats=false). Call policy_compliance_stats "
            "for per-policy compliance breakdowns, or re-call with include_stats=true."
        )

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

    # Mask out the unused bit 0 so odd values don't produce wrong results
    bitmask = bitmask & 0xFE

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

    # Surface Do Not Disturb honoring at top level. These determine whether a patch
    # policy's install/reboot defers to macOS Do Not Disturb / Windows Focus, which
    # answers "did the policy act, or did DND block it?" without raw-dumping the policy.
    dnd_honored = {
        key: policy_data.get(key)
        for key in ("installation_do_not_disturb_honored", "reboot_do_not_disturb_honored")
        if policy_data.get(key) is not None
    }
    if dnd_honored:
        data["dnd_honored"] = dnd_honored

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
    # NOTE: result_status is intentionally NOT forwarded to the API. The
    # /policy-history/policies/{uuid}/{token} endpoint silently ignores
    # this filter regardless of name (`result_status`, `resultStatus`,
    # `status` all return the unfiltered set), so we apply the filter
    # client-side below to honor the documented contract.
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

    requested_status = _normalize_status(result_status) if result_status else None
    pre_filter_total = sum(1 for entry in devices_raw if isinstance(entry, Mapping))

    status_counter: Counter[str] = Counter()
    device_results: list[dict[str, Any]] = []

    for entry in devices_raw:
        if not isinstance(entry, Mapping):
            continue
        status = _normalize_status(entry.get("result_status"))
        if requested_status is not None and status != requested_status:
            continue
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

    data: dict[str, Any] = {
        "policy_uuid": str(policy_uuid),
        "exec_token": str(exec_token),
        "result_summary": {
            "total_devices": len(device_results),
            "status_breakdown": dict(status_counter),
        },
        "devices": device_results,
        "pagination": pagination_meta,
    }

    upstream_page = pagination_meta.get("current_page") if pagination_meta else None
    upstream_limit = pagination_meta.get("limit") if pagination_meta else limit
    upstream_total = pagination_meta.get("total_count") if pagination_meta else None
    metadata: dict[str, Any] = {
        "deprecated_endpoint": False,
        "org_uuid": str(org_uuid),
        "policy_uuid": str(policy_uuid),
        "exec_token": str(exec_token),
        "result_count": len(device_results),
        "status_breakdown": dict(status_counter),
        # Live-verified 2026-06-05 — without this legend the model has to guess
        # what a large negative exit_code means, and which namespace a fallback
        # value came from.
        "field_notes": {
            "exit_code": (
                "Raw process exit code from the policy script on the device: "
                "0 = success; negative values on Windows are NTSTATUS codes as "
                "signed 32-bit ints (e.g. -1073741502 = 0xC0000142 "
                "STATUS_DLL_INIT_FAILED). When the upstream exit_code is null "
                "this field falls back to the Automox internal error_code (a "
                "different namespace)."
            ),
            "result_status": (
                "Lowercase per-device outcome string (live-verified: 'failed'; "
                "'success' and others per spec, unverified live)."
            ),
        },
        # Legacy fields retained for backwards-compat (#52). Canonical
        # pagination block lives under metadata.pagination. Reserved keys
        # limit/total_count are strictly typed (int|None) on PaginationMetadata,
        # so guard the raw upstream forwards with the same isinstance check
        # already applied below — a non-int (e.g. "") would otherwise raise an
        # uncaught ValidationError in as_tool_response.
        "page": upstream_page if isinstance(upstream_page, int) else None,
        "limit": upstream_limit if isinstance(upstream_limit, int) else None,
        "total_count": upstream_total if isinstance(upstream_total, int) else None,
        "pagination": build_pagination_metadata(
            page=upstream_page if isinstance(upstream_page, int) else None,
            page_size=upstream_limit if isinstance(upstream_limit, int) else None,
            total_elements=upstream_total if isinstance(upstream_total, int) else None,
        ),
    }

    if requested_status is not None:
        metadata["result_status_filter"] = {
            "applied": "client_side",
            "requested_status": requested_status,
            "pre_filter_count": pre_filter_total,
            "post_filter_count": len(device_results),
            "note": (
                "Upstream policy-history API ignores the result_status query "
                "parameter and returns mixed statuses; this wrapper filters "
                "the page client-side. Pagination counts in `pagination` "
                "reflect the unfiltered upstream response."
            ),
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
    response = await client.get("/approvals", params=params)
    # /approvals returns a {"size": N, "results": [...]} envelope
    # (components/schemas/Approvals; envelope confirmed live 2026-06-05).
    # The previous bare-Sequence assumption made this tool silently report
    # zero approvals on every conforming response — the same envelope class
    # as the #132 bugs. Keep a bare-list fallback for defensive parity.
    approvals: Sequence[Any]
    if isinstance(response, Mapping):
        results = response.get("results")
        approvals = (
            results
            if isinstance(results, Sequence) and not isinstance(results, (str, bytes))
            else []
        )
    elif isinstance(response, Sequence) and not isinstance(response, (str, bytes)):
        approvals = response
    else:
        approvals = []

    status_filter = (status or "").lower()
    status_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    pending_items = []

    for approval_item in approvals:
        if not isinstance(approval_item, Mapping):
            continue
        approval_status = str(approval_item.get("status") or "unknown").lower()
        status_counts[approval_status] += 1

        # The approval record carries NO top-level severity field (confirmed
        # live 2026-06-06 across a 12-row device-bearing queue, issue #165) —
        # CVE ids ride under software.cves. The nested `software.severity` key
        # DOES exist in the live shape (null on every observed row), so fall
        # back to it before bucketing to "unspecified". Count a real severity
        # when one appears from either source (forward-compat), and bucket the
        # rest as "unspecified" — distinct from an upstream value that literally
        # says "unknown".
        software_for_severity = approval_item.get("software")
        nested_severity = (
            software_for_severity.get("severity")
            if isinstance(software_for_severity, Mapping)
            else None
        )
        severity_raw = (
            approval_item.get("severity") or approval_item.get("cvss_severity") or nested_severity
        )
        severity_counts[str(severity_raw).lower() if severity_raw else "unspecified"] += 1

        if status_filter and approval_status != status_filter:
            continue

        software_raw = approval_item.get("software")
        software = software_raw if isinstance(software_raw, Mapping) else {}
        policy_raw = approval_item.get("policy")
        policy_info = policy_raw if isinstance(policy_raw, Mapping) else {}

        entry: dict[str, Any] = {
            "approval_id": approval_item.get("id"),
            # Spec shape: the human-readable name lives at software.display_name.
            "title": software.get("display_name")
            or approval_item.get("title")
            or approval_item.get("name"),
            "status": approval_item.get("status"),
            # Spec: True = approved, False = rejected, null = awaiting decision.
            "manual_approval": approval_item.get("manual_approval"),
            "manual_approval_time": approval_item.get("manual_approval_time"),
        }
        if severity_raw:
            entry["severity"] = severity_raw
        software_summary = {
            key: software.get(key)
            for key in ("version", "os_family")
            if software.get(key) is not None
        }
        if software_summary:
            entry["software"] = software_summary
        cves_raw = software.get("cves")
        if isinstance(cves_raw, Sequence) and not isinstance(cves_raw, (str, bytes)):
            entry["cves"] = [str(cve) for cve in cves_raw[:5]]
            if len(cves_raw) > 5:
                entry["cves_truncated"] = len(cves_raw) - 5
        if policy_info:
            entry["policy"] = {
                "id": policy_info.get("id"),
                "name": policy_info.get("name"),
            }

        pending_items.append(entry)

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
        "field_notes": {
            "manual_approval": (
                "The decision axis: True=approved, False=rejected, null=awaiting "
                "a manual decision. Live-verified on a device-bearing test org "
                "(2026-06-06, issue #165): on decided rows it co-occurs 1:1 with "
                "`status` — true<->status='approved' (8/8), false<->status='rejected' "
                "(4/4) — and `manual_approval_time` is a 'YYYY-MM-DD HH:MM:SS' "
                "string. So `status` on a decided row is the DECISION OUTCOME, not "
                "an execution status. The value of `status` while a row is still "
                "awaiting was NOT observed, so it is unknown; identify "
                "awaiting rows by `manual_approval is None`, not by `status`."
            ),
            "severity_breakdown": (
                "Bucketed CVE severity. The approval record carries NO top-level "
                "severity field (confirmed live 2026-06-06, 12/12 rows); a nested "
                "`software.severity` key exists in the live shape (null on every "
                "observed row) and is read as a fallback. Rows with no severity from "
                "either source are bucketed 'unspecified' (distinct from an upstream "
                "value that literally says 'unknown'). The envelope is "
                "{results, size}."
            ),
        },
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
    total_pending = 0

    if isinstance(stats, Sequence):
        for item in stats:
            if not isinstance(item, Mapping):
                continue
            compliant = item.get("compliant", 0) or 0
            noncompliant = item.get("non_compliant", 0) or item.get("noncompliant", 0) or 0
            # /policystats carries a `pending` count (live-verified
            # 2026-06-05). It was previously dropped, so a policy with
            # 2 compliant / 0 noncompliant / 166 pending read as "100%
            # compliant over 2 devices". Pending stays out of the
            # compliance denominator (platform rule: pending does not count
            # against compliance) but is reported as its own rate.
            pending = item.get("pending", 0) or 0
            evaluated = compliant + noncompliant
            device_count = evaluated + pending

            total_compliant += compliant
            total_noncompliant += noncompliant
            total_pending += pending

            policy_stats.append(
                {
                    "policy_id": item.get("policy_id"),
                    "policy_name": item.get("policy_name") or item.get("name"),
                    "policy_type": item.get("policy_type_name"),
                    "compliant_devices": compliant,
                    "noncompliant_devices": noncompliant,
                    "pending_devices": pending,
                    "total_devices": device_count,
                    "compliance_rate_percent": (
                        round(compliant / evaluated * 100, 1) if evaluated > 0 else None
                    ),
                    "pending_rate_percent": (
                        round(pending / device_count * 100, 1) if device_count > 0 else None
                    ),
                }
            )

    total_evaluated = total_compliant + total_noncompliant
    total_devices = total_evaluated + total_pending

    return {
        "data": {
            "overall_compliance": {
                "total_devices_evaluated": total_evaluated,
                "compliant": total_compliant,
                "noncompliant": total_noncompliant,
                "pending": total_pending,
                "total_devices": total_devices,
                "compliance_rate_percent": (
                    round(total_compliant / total_evaluated * 100, 1)
                    if total_evaluated > 0
                    else None
                ),
                "pending_rate_percent": (
                    round(total_pending / total_devices * 100, 1) if total_devices > 0 else None
                ),
            },
            "per_policy_stats": policy_stats,
        },
        "metadata": {
            "deprecated_endpoint": False,
            "org_id": resolved_org_id,
            "policy_count": len(policy_stats),
            "rate_semantics": (
                "compliance_rate_percent is computed over evaluated devices "
                "(compliant + noncompliant) and is null when none have been "
                "evaluated; pending devices do not count against compliance "
                "(platform rule) and are reported via pending_devices / "
                "pending_rate_percent over all targeted devices."
            ),
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

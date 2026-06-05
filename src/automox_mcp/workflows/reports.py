"""Report workflows for Automox MCP."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from ..client import AutomoxClient

# Safety cap on auto-pagination to prevent runaway loops.
_MAX_PAGINATION_PAGES = 50

# Cap on the per-policy reasonForFail free-text blob. Live (2026-06-05) these
# run ~600-840 chars and can be larger; cap to bound token usage while keeping
# the raw prefix and an explicit truncation marker.
_REASON_FOR_FAIL_CAP = 2000


def _truncate_reason(value: Any) -> Any:
    """Cap a reasonForFail string at _REASON_FOR_FAIL_CAP with a marker.

    Non-string values (incl. None) pass through unchanged.
    """
    if not isinstance(value, str) or len(value) <= _REASON_FOR_FAIL_CAP:
        return value
    dropped = len(value) - _REASON_FOR_FAIL_CAP
    return f"{value[:_REASON_FOR_FAIL_CAP]}... [truncated {dropped} chars]"


# Severity ordering for the per-device "highest_severity" projection.
#
# Finding 31: the upstream prepatch payload carries DISTINCT `no_known_cves`
# and `unknown` states (both live-verified as separate summary buckets on
# 2026-06-05). They must not collapse into one string:
#   - "no_known_cves" = the patch carries no associated CVE (benign / low
#     priority). Ranked -1: below every assessed severity (incl. "none") so it
#     is never mistaken for an assessed risk, but strictly ABOVE "unknown".
#   - "unknown" = severity absent or undetermined (the spec also defines a
#     literal "unknown" value). Ranked -2 — also the default rank for an
#     absent/unparseable severity, which is correct: both mean "no assessed
#     CVE severity available". Separating the spec "unknown" from the no-data
#     fallthrough is out of scope (a single string field cannot carry both).
_SEVERITY_RANK: dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "none": 0,
    "no_known_cves": -1,
    "unknown": -2,
}

# Default rank for a severity string the table does not recognize (absent,
# empty, or unparseable) — same bucket as the spec "unknown" value.
_SEVERITY_DEFAULT_RANK = -2


def _highest_patch_severity(patches: Any) -> str:
    """Return the highest severity found across a device's patches.

    Returns ``"no_known_cves"`` only when that is genuinely the device's max
    (its patches carry no CVEs); ``"unknown"`` covers both the spec literal
    "unknown" value and the absent/unparseable-data fallthrough.
    """
    if not patches:
        return "unknown"
    items: Sequence[Any]
    if isinstance(patches, Mapping):
        items = list(patches.values())
    elif isinstance(patches, Sequence) and not isinstance(patches, (str, bytes)):
        items = patches
    else:
        return "unknown"

    # Seed below every known rank (incl. "unknown" at -2) so an empty or
    # all-unparseable item set falls through to the literal "unknown" return.
    max_rank = -3
    for patch in items:
        if not isinstance(patch, Mapping):
            continue
        sev = str(patch.get("severity") or patch.get("cve_severity") or "").lower().strip()
        rank = _SEVERITY_RANK.get(sev, _SEVERITY_DEFAULT_RANK)
        if rank > max_rank:
            max_rank = rank

    for sev_name, rank in _SEVERITY_RANK.items():
        if rank == max_rank:
            return sev_name
    return "unknown"


def _extract_devices(response: Any, *wrapper_keys: str) -> list[Any]:
    """Extract a device list from a potentially nested API response.

    The Automox reports API returns nested structures like
    ``{"prepatch": {"devices": [...]}}`` or an array of
    ``{"nonCompliant": {"devices": [...]}}``.  This helper walks
    *wrapper_keys* to reach the device list.
    """
    current: Any = response

    # If the response is a list, try to merge devices from all elements
    if isinstance(current, list) and current:
        # Walk wrapper keys in the first element to check if the structure matches
        test = current[0]
        for key in wrapper_keys:
            if isinstance(test, Mapping):
                test = test.get(key)
            else:
                test = None
                break
        if isinstance(test, Sequence) and not isinstance(test, (str, bytes)) and len(current) > 1:
            # Multiple result objects — merge their device lists
            merged: list[Any] = []
            for element in current:
                inner = element
                for key in wrapper_keys:
                    if isinstance(inner, Mapping):
                        inner = inner.get(key)
                    else:
                        inner = None
                        break
                if isinstance(inner, Sequence) and not isinstance(inner, (str, bytes)):
                    merged.extend(inner)
            return merged
        current = current[0]

    # Walk through wrapper keys (e.g. "prepatch" -> "devices")
    for key in wrapper_keys:
        if isinstance(current, Mapping):
            current = current.get(key)
        else:
            return []

    if isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
        return list(current)
    return []


def _extract_summary(response: Any, wrapper_key: str) -> dict[str, Any]:
    """Extract top-level summary counters from a report response."""
    current: Any = response
    if isinstance(current, list) and current:
        current = current[0]
    if isinstance(current, Mapping):
        section = current.get(wrapper_key)
        if isinstance(section, Mapping):
            return {k: v for k, v in section.items() if k != "devices"}
    return {}


async def get_prepatch_report(
    client: AutomoxClient,
    *,
    org_id: int,
    group_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """Retrieve the pre-patch readiness report.

    Automatically paginates to fetch all devices unless an explicit
    limit/offset is provided (single-page mode).
    """
    params: dict[str, Any] = {"o": org_id}
    if group_id is not None:
        params["groupId"] = group_id

    # If caller provided explicit limit/offset, do a single request (backwards compat)
    single_page = limit is not None or offset is not None
    if single_page:
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset

    page_size = limit or 500
    params.setdefault("limit", page_size)
    params.setdefault("offset", 0)

    device_list: list[Any] = []
    summary: dict[str, Any] = {}

    for _page_num in range(_MAX_PAGINATION_PAGES):
        report = await client.get("/reports/prepatch", params=params)

        # Response shape: {"prepatch": {"total": N, ..., "devices": [...]}}
        page_devices = _extract_devices(report, "prepatch", "devices")
        if not summary:
            summary = _extract_summary(report, "prepatch")

        device_list.extend(page_devices)

        if single_page:
            break

        # Note: summary["total"] reports pending-patch count, not device count,
        # so it cannot be used to short-circuit pagination. Rely on the
        # empty-page check below.
        if not page_devices:
            break

        params["offset"] = params["offset"] + page_size

    devices: list[dict[str, Any]] = []
    severity_counter: Counter[str] = Counter()
    for item in device_list:
        if not isinstance(item, Mapping):
            continue
        patches = item.get("patches")
        patch_count: int | None = None
        if isinstance(patches, Sequence) and not isinstance(patches, (str, bytes)):
            patch_count = len(patches)
        elif isinstance(patches, Mapping):
            patch_count = sum(1 for _ in patches)

        device_severity = _highest_patch_severity(patches)
        severity_counter[device_severity] += 1

        entry: dict[str, Any] = {
            "server_id": item.get("id"),
            "server_name": item.get("name"),
            "group": item.get("group"),
            "os_family": item.get("os_family"),
            "connected": item.get("connected"),
            "compliant": item.get("compliant"),
            "needs_reboot": item.get("needsReboot"),
            "pending_patches": patch_count,
            "highest_severity": device_severity,
        }
        devices.append(entry)

    total_pending_patches = summary.get("total") or 0
    devices_needing_patches = len(devices)
    device_severity_summary = {
        "total_pending_patches": total_pending_patches,
        "devices_needing_patches": devices_needing_patches,
        "critical": severity_counter.get("critical", 0),
        "high": severity_counter.get("high", 0),
        "medium": severity_counter.get("medium", 0),
        "low": severity_counter.get("low", 0),
        "none": severity_counter.get("none", 0),
        "no_known_cves": severity_counter.get("no_known_cves", 0),
        "unknown": severity_counter.get("unknown", 0),
    }

    return {
        "data": {
            "total_pending_patches": total_pending_patches,
            "total_devices": devices_needing_patches,
            "summary": device_severity_summary,
            "api_summary": summary,
            "devices": devices,
        },
        "metadata": {
            "deprecated_endpoint": False,
            "field_notes": {
                "highest_severity": (
                    "Per device: the highest patch severity across its pending "
                    "patches. Full enum per spec (unverified live): "
                    "critical/high/medium/low/none/no_known_cves/unknown. "
                    "Live-observed on this tenant (2026-06-05): no_known_cves, "
                    "high, critical, unknown. 'no_known_cves' = patches carry no "
                    "associated CVE (benign / low priority); 'unknown' = severity "
                    "absent or undetermined (NOT inherently high risk). These two "
                    "are distinct states (the upstream summary carries separate "
                    "no_known_cves/unknown counters) and are never collapsed."
                ),
                "compliant": (
                    "Upstream device compliance boolean, passed through raw. "
                    "Platform rule (per #149/#155): a device is non-compliant "
                    "only when a policy needs remediation; pending work alone does "
                    "not count against compliance. A device can be compliant:true "
                    "while still listed here with pending patches — this is not a "
                    "contradiction. The relationship of this boolean to the rule "
                    "is attributed to the platform, not recomputed by this wrapper."
                ),
                "total_pending_patches": (
                    "Upstream prepatch summary 'total' (spec describes it only as "
                    "'Total property' — unit not spec-stated; this wrapper "
                    "relabels it). The per-severity buckets are NOT guaranteed to "
                    "sum to it (live 2026-06-05: total=54 vs severity-bucket "
                    "sum=36). Treat it as an upstream-reported pending count, not "
                    "a recomputed device count, and do not assume it is org-wide."
                ),
                "summary": (
                    "Per-severity device counts RECOMPUTED by this wrapper from "
                    "highest_severity, including a distinct 'no_known_cves' bucket. "
                    "The raw upstream summary counters (which already included "
                    "no_known_cves and unknown separately) are passed through "
                    "unmodified under 'api_summary'."
                ),
            },
        },
    }


async def get_noncompliant_report(
    client: AutomoxClient,
    *,
    org_id: int,
    group_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """Retrieve the non-compliant devices report.

    Automatically paginates to fetch all devices unless an explicit
    limit/offset is provided (single-page mode).
    """
    params: dict[str, Any] = {"o": org_id}
    if group_id is not None:
        params["groupId"] = group_id

    # If caller provided explicit limit/offset, do a single request (backwards compat)
    single_page = limit is not None or offset is not None
    if single_page:
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset

    page_size = limit or 500
    params.setdefault("limit", page_size)
    params.setdefault("offset", 0)

    device_list: list[Any] = []
    summary: dict[str, Any] = {}

    for _page_num in range(_MAX_PAGINATION_PAGES):
        report = await client.get(
            "/reports/needs-attention",
            params=params,
        )

        # Response shape: array or {"nonCompliant": {"total": N, ..., "devices": [...]}}
        page_devices = _extract_devices(report, "nonCompliant", "devices")
        if not summary:
            summary = _extract_summary(report, "nonCompliant")

        device_list.extend(page_devices)

        if single_page:
            break

        # Note: summary["total"] on /reports/needs-attention reports the
        # **per-page device count** (probed against a live tenant for #68 —
        # tenant had 138 devices; with limit=10, summary["total"] was 10 on
        # every page). It is NOT a total-device count and must NOT be used to
        # terminate pagination — doing so would break after the first page.
        # Mirrors the sibling warning in get_prepatch_report above.
        if not page_devices:
            break

        params["offset"] = params["offset"] + page_size

    devices: list[dict[str, Any]] = []
    for item in device_list:
        if not isinstance(item, Mapping):
            continue
        entry: dict[str, Any] = {
            "server_id": item.get("id"),
            "server_name": item.get("name") or item.get("customName"),
            "server_group_id": item.get("groupId"),
            "os_family": item.get("os_family"),
            "connected": item.get("connected"),
            "needs_reboot": item.get("needsReboot"),
            "last_refresh_time": item.get("lastRefreshTime"),
        }
        policies = item.get("policies")
        if isinstance(policies, list):
            entry["failing_policies"] = [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "type": p.get("type"),
                    "severity": p.get("severity"),
                    "reason_for_fail": _truncate_reason(p.get("reasonForFail")),
                    "package_count": (
                        len(p["packages"]) if isinstance(p.get("packages"), list) else None
                    ),
                }
                for p in policies
                if isinstance(p, Mapping)
            ]
        devices.append(entry)

    return {
        "data": {
            # Use the actual accumulated device count, not summary["total"] —
            # see the per-page-count caveat above. summary["total"] would
            # report ~limit on tenants with more devices than fit in one page.
            "total_devices": len(devices),
            "summary": summary,
            "devices": devices,
        },
        "metadata": {
            "deprecated_endpoint": False,
            "field_notes": {
                "reason_for_fail": (
                    "Per failing policy: the upstream free-text failure reason "
                    "(reasonForFail). A verbose multi-line log blob (live "
                    "2026-06-05: ~600-840 chars, can be larger); truncated to "
                    f"{_REASON_FOR_FAIL_CAP} chars with a '... [truncated N "
                    "chars]' marker when longer."
                ),
                "severity": (
                    "Per failing policy: the policy severity. Full enum per spec "
                    "(unverified live): no_known_cves/none/unknown/low/medium/"
                    "high/critical. Live-observed on this tenant (2026-06-05): "
                    "unknown, high, critical."
                ),
                "type": (
                    "Per failing policy: the policy type (e.g. 'patch' observed "
                    "live 2026-06-05; other values per spec, unverified live)."
                ),
                "package_count": (
                    "Per failing policy: count of entries in the upstream "
                    "'packages' list (the full package array is not surfaced to "
                    "stay lean); null when no packages list is present."
                ),
            },
        },
    }

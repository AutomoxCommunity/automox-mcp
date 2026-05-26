#!/usr/bin/env python3
"""Verify reported MCP server bugs against a live tenant via stdio.

Goal: independently reproduce each reported issue with the exact repro
context (org UUID, action_set_id, policy_uuid, exec_token, device IDs)
and a stdio transport that matches Claude Desktop's. This separates
real server bugs from session-specific artifacts (rate limits, transport
differences, transient API hiccups) before any fix is written.

Output: one line per case — VERIFIED (bug reproduced), NOT_REPRODUCED
(works fine), or AMBIGUOUS (different failure shape than reported).

This is a manual debugging harness — *not* part of the CI test suite.
Tenant-specific IDs default to the v1.0.20 Claude Desktop report context;
override via the VERIFY_* env vars below for a different tenant.

Requirements (env):
    AUTOMOX_API_KEY, AUTOMOX_ACCOUNT_UUID    — required, see project README
    AUTOMOX_ORG_ID                            — optional; falls back to VERIFY_ORG_ID
    VERIFY_ORG_UUID                           — defaults to the test-report tenant
    VERIFY_ORG_ID                             — same
    VERIFY_DEVICE_ID                          — int, an existing device
    VERIFY_ACTION_SET_ID                      — int, vuln remediation action set
    VERIFY_POLICY_UUID                        — uuid, a policy with run history
    VERIFY_EXEC_TOKEN                         — uuid, a recent exec_token from that policy
    VERIFY_ACTOR_EMAIL                        — email of a user who exists but has
                                                no audit activity for the test date

Usage:
    set -a && . ~/automox/.env && set +a && \\
        uv run python tests/verify_reported_bugs.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ---------------------------------------------------------------------------
# Tenant context — parameterized via env vars so this harness is reusable.
# Defaults are the values from the v1.0.20 Claude Desktop test report.
# Set VERIFY_* env vars to point at a different tenant.
# ---------------------------------------------------------------------------
ORG_UUID = os.environ.get("VERIFY_ORG_UUID", "1bfab13f-3d5f-482f-9c40-f6ab840fbe1b")
ORG_ID = os.environ.get("VERIFY_ORG_ID", "101934")
DEVICE_ID = int(os.environ.get("VERIFY_DEVICE_ID", "2520712"))
ACTION_SET_ID = int(os.environ.get("VERIFY_ACTION_SET_ID", "1245067"))
POLICY_UUID = os.environ.get("VERIFY_POLICY_UUID", "e1c9b860-bc73-4ae2-bef5-2cdc3b7e2f8e")
EXEC_TOKEN = os.environ.get("VERIFY_EXEC_TOKEN", "5a9f9230-4439-11f1-922e-e2be58cbfb3c")

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"


def status(label: str, msg: str, color: str = "") -> None:
    print(f"  [{color}{label}{RESET}] {msg}")


def case(num: int, name: str) -> None:
    print(f"\n{BOLD}#{num} — {name}{RESET}")


# ---------------------------------------------------------------------------
# MCP client setup
# ---------------------------------------------------------------------------
def _resolve_org_id() -> str:
    forced = os.environ.get("AUTOMOX_ORG_ID")
    return forced or ORG_ID


@asynccontextmanager
async def open_session():
    server = StdioServerParameters(
        command="uv",
        args=["run", "automox-mcp"],
        env={
            **os.environ,
            "AUTOMOX_ORG_ID": _resolve_org_id(),
            # Match Claude Desktop default: no read-only override
            "AUTOMOX_MCP_SANITIZE_RESPONSES": os.environ.get(
                "AUTOMOX_MCP_SANITIZE_RESPONSES", "true"
            ),
        },
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def call_tool(
    session: ClientSession, name: str, args: dict[str, Any]
) -> tuple[bool, Any, str]:
    """Call a tool. Returns (is_error, parsed_payload_or_text, raw_text).

    The MCP server typically returns a TextContent block whose text is a JSON
    document. is_error reflects the MCP protocol-level isError flag.
    """
    try:
        result = await session.call_tool(name, args)
    except Exception as exc:  # noqa: BLE001
        return True, None, f"<exception: {type(exc).__name__}: {exc}>"

    if not result.content:
        return bool(result.isError), None, "<empty content>"

    block = result.content[0]
    text = getattr(block, "text", "") or ""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        parsed = None
    return bool(result.isError), parsed, text


def find_status_in(text: str, *needles: str) -> bool:
    return any(n in text for n in needles)


# ---------------------------------------------------------------------------
# Verification cases
# ---------------------------------------------------------------------------
async def case_1_patch_tuesday(session: ClientSession) -> str:
    """Reported: get_patch_tuesday_readiness → HTTP 500.

    Detection uses MCP's isError flag and an explicit `unexpected error`
    substring check rather than a bare `500` match (which collides with
    legitimate count fields like total_pending_patches=500).
    """
    is_error, parsed, raw = await call_tool(session, "get_patch_tuesday_readiness", {})
    if is_error or "unexpected error" in raw.lower() or "(status=500)" in raw:
        status("VERIFIED", f"reproduced — {raw[:200]}", RED)
        return "VERIFIED"
    if isinstance(parsed, dict) and parsed.get("data"):
        data = parsed["data"]
        keys = list(data.keys())[:6] if isinstance(data, dict) else "list"
        status("NOT_REPRODUCED", f"returned data successfully — keys={keys}", GREEN)
        return "NOT_REPRODUCED"
    status("AMBIGUOUS", f"unexpected shape — {raw[:200]}", YELLOW)
    return "AMBIGUOUS"


async def case_2_action_set_actions(session: ClientSession) -> str:
    """Reported: get_action_set_actions → HTTP 405 Method Not Allowed."""
    is_error, parsed, raw = await call_tool(
        session, "get_action_set_actions", {"action_set_id": ACTION_SET_ID}
    )
    if "405" in raw or "method not allowed" in raw.lower():
        status("VERIFIED", f"reproduced 405 — {raw[:200]}", RED)
        return "VERIFIED"
    if is_error:
        status("AMBIGUOUS", f"errored but not 405 — {raw[:200]}", YELLOW)
        return "AMBIGUOUS"
    status("NOT_REPRODUCED", f"call succeeded — {raw[:200]}", GREEN)
    return "NOT_REPRODUCED"


async def case_3_policy_run_detail_v2(session: ClientSession) -> str:
    """Reported: policy_run_detail_v2 → 400 Invalid or missing org=null."""
    is_error, parsed, raw = await call_tool(
        session,
        "policy_run_detail_v2",
        {"exec_token": EXEC_TOKEN, "policy_uuid": POLICY_UUID},
    )
    if "org=null" in raw.lower() or ("400" in raw and "org" in raw.lower()):
        status("VERIFIED", f"reproduced — {raw[:200]}", RED)
        return "VERIFIED"
    if is_error:
        status("AMBIGUOUS", f"errored differently — {raw[:200]}", YELLOW)
        return "AMBIGUOUS"
    status("NOT_REPRODUCED", f"call succeeded — {raw[:200]}", GREEN)
    return "NOT_REPRODUCED"


async def case_4a_action_set_detail_noop(session: ClientSession) -> str:
    """Reported: get_action_set_detail returns same fields as list parent."""
    _, list_parsed, _ = await call_tool(session, "list_remediation_action_sets", {})
    _, detail_parsed, raw = await call_tool(
        session, "get_action_set_detail", {"action_set_id": ACTION_SET_ID}
    )
    if not isinstance(detail_parsed, dict):
        status("AMBIGUOUS", f"detail not a dict — {raw[:200]}", YELLOW)
        return "AMBIGUOUS"
    detail_data = detail_parsed.get("data") or detail_parsed
    if not isinstance(detail_data, dict):
        status("AMBIGUOUS", "detail.data not a dict", YELLOW)
        return "AMBIGUOUS"
    detail_keys = set(detail_data.keys())
    minimal_keys = {"id", "status", "source", "created_at", "updated_at"}
    extra_keys = detail_keys - minimal_keys
    if not extra_keys:
        status(
            "VERIFIED",
            f"detail returns only minimal keys: {sorted(detail_keys)}",
            RED,
        )
        return "VERIFIED"
    status(
        "NOT_REPRODUCED",
        f"detail returns extra keys beyond list: {sorted(extra_keys)}",
        GREEN,
    )
    return "NOT_REPRODUCED"


async def case_4b_policy_history_detail_noop(session: ClientSession) -> str:
    """Reported: policy_history_detail returns no run history."""
    _, parsed, raw = await call_tool(session, "policy_history_detail", {"policy_uuid": POLICY_UUID})
    if not isinstance(parsed, dict):
        status("AMBIGUOUS", f"unexpected shape — {raw[:200]}", YELLOW)
        return "AMBIGUOUS"
    data = parsed.get("data") or parsed
    if isinstance(data, dict):
        keys = set(data.keys())
        if any(k in keys for k in ("runs", "history", "recent_runs")):
            status("NOT_REPRODUCED", f"includes run history — keys={sorted(keys)}", GREEN)
            return "NOT_REPRODUCED"
        status(
            "VERIFIED",
            f"no run-history field — keys={sorted(keys)}",
            RED,
        )
        return "VERIFIED"
    status("AMBIGUOUS", "data not a dict", YELLOW)
    return "AMBIGUOUS"


async def case_6_device_assignments_spring_leak(session: ClientSession) -> str:
    """Reported: get_device_assignments leaks Spring pagination wrapper.

    The tool actually takes no device argument — it returns org-wide
    assignments. The original harness incorrectly passed device_id and
    tripped a schema validation error.

    v1.0.23 fix moves Spring pagination fields into a normalized
    metadata.pagination block; the data.assignments items must NOT
    contain them. The harness checks `data` (not `metadata`) for
    Spring markers — `metadata.pagination.total_elements` is the
    canonical, normalized location and is allowed.
    """
    _, parsed, raw = await call_tool(session, "get_device_assignments", {})
    # Spring fields are only a problem when they leak into the data
    # payload. The normalized metadata.pagination location is allowed.
    spring_markers = (
        "pageable",
        "totalElements",
        "total_elements",
        "numberOfElements",
        "number_of_elements",
        "sort.empty",
        "pageable.empty",
    )

    # Check `data` only, not the full raw text (which now legitimately
    # contains some of these markers under metadata.pagination).
    data_text = json.dumps(parsed.get("data") if isinstance(parsed, dict) else parsed)
    hits = [m for m in spring_markers if m in data_text]
    if hits:
        status("VERIFIED", f"Spring wrapper fields present in data: {hits[:5]}", RED)
        return "VERIFIED"
    status(
        "NOT_REPRODUCED",
        f"no Spring wrapper in data — data_text[:200]={data_text[:200]}",
        GREEN,
    )
    return "NOT_REPRODUCED"


async def case_7_policy_run_results_filter(session: ClientSession) -> str:
    """Reported: result_status='failed' filter is silently ignored."""
    _, parsed, raw = await call_tool(
        session,
        "policy_run_results",
        {
            "policy_uuid": POLICY_UUID,
            "exec_token": EXEC_TOKEN,
            "result_status": "failed",
        },
    )
    if not isinstance(parsed, dict):
        status("AMBIGUOUS", f"unexpected shape — {raw[:300]}", YELLOW)
        return "AMBIGUOUS"
    data = parsed.get("data") or {}
    runs = None
    for key in ("devices", "runs", "results", "items", "entries"):
        if isinstance(data.get(key), list):
            runs = data[key]
            break
    if not isinstance(runs, list):
        keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
        status("AMBIGUOUS", f"no run list found — keys={keys}", YELLOW)
        return "AMBIGUOUS"
    statuses: list[str] = [
        s
        for r in runs
        if isinstance(r, dict)
        for s in [r.get("result_status") or r.get("status")]
        if s
    ]
    non_failed = [s for s in statuses if s != "failed"]
    summary = data.get("result_summary") or data.get("pagination", {}).get("result_summary")
    if non_failed:
        status(
            "VERIFIED",
            f"filter ignored — got statuses: {sorted(set(statuses))[:5]} (summary={summary})",
            RED,
        )
        return "VERIFIED"
    status(
        "NOT_REPRODUCED",
        f"filter honored — all {len(statuses)} statuses are 'failed' (summary={summary})",
        GREEN,
    )
    return "NOT_REPRODUCED"


async def case_8_audit_actor_cursor(session: ClientSession) -> str:
    """Reported: actor_email filter mismatch advances next_cursor anyway.

    Updated to use a real-but-likely-inactive actor (the test user from the
    report) on a date when they likely had no activity. The original
    harness used a fully bogus email which exercised a different code
    path and didn't reproduce the bug.
    """
    real_actor = os.environ.get("VERIFY_ACTOR_EMAIL", "jason.kikta@automox.com")
    _, parsed, raw = await call_tool(
        session,
        "audit_trail_user_activity",
        {
            "actor_email": real_actor,
            "date": "2026-04-29",
            "limit": 5,
        },
    )
    if not isinstance(parsed, dict):
        status("AMBIGUOUS", f"unexpected shape — {raw[:200]}", YELLOW)
        return "AMBIGUOUS"
    # next_cursor lives in metadata, not in data
    metadata = parsed.get("metadata") or {}
    data = parsed.get("data") or {}
    next_cursor = metadata.get("next_cursor") or data.get("next_cursor")
    events_returned = (
        metadata.get("events_returned")
        if metadata.get("events_returned") is not None
        else data.get("events_returned")
    )
    events_seen = metadata.get("events_seen") or data.get("events_seen")
    # v1.0.22 fix surfaces this state explicitly via
    # metadata.filter_pagination_state. If that flag is present, the
    # state is no longer ambiguous — caller has explicit guidance.
    filter_state = metadata.get("filter_pagination_state")
    if next_cursor and events_returned == 0 and not filter_state:
        status(
            "VERIFIED",
            (
                f"cursor advanced ({next_cursor[:20]}...) despite events_returned=0 "
                f"(events_seen={events_seen})"
            ),
            RED,
        )
        return "VERIFIED"
    if filter_state:
        status(
            "NOT_REPRODUCED",
            (
                f"state explicitly flagged: filter_pagination_state="
                f"{filter_state.get('no_matches_in_page')}, advice present"
            ),
            GREEN,
        )
        return "NOT_REPRODUCED"
    status(
        "NOT_REPRODUCED",
        f"cursor={next_cursor!r}, events_returned={events_returned}, events_seen={events_seen}",
        GREEN,
    )
    return "NOT_REPRODUCED"


async def case_9_policy_health_sample(session: ClientSession) -> str:
    """Reported: sample size mismatch — total_runs != considered."""
    _, parsed, raw = await call_tool(session, "policy_health_overview", {})
    if not isinstance(parsed, dict):
        status("AMBIGUOUS", f"unexpected shape — {raw[:200]}", YELLOW)
        return "AMBIGUOUS"
    data = parsed.get("data") or parsed
    metadata = parsed.get("metadata") or {}
    total = data.get("total_policy_runs")
    considered = data.get("total_runs_considered")
    max_runs = data.get("max_runs")
    # v1.0.22 fix surfaces the discrepancy explicitly via
    # data.sample_is_truncated and metadata.sample_note. The numerical
    # mismatch is caused by an Automox API server-side cap (~100 events)
    # that no client param can override; the wrapper now flags it.
    sample_truncated = data.get("sample_is_truncated") or metadata.get("sample_is_truncated")
    if total is not None and considered is not None and considered < total:
        if max_runs is None or considered < max_runs:
            if sample_truncated:
                status(
                    "NOT_REPRODUCED",
                    (
                        f"discrepancy explicitly flagged via sample_is_truncated="
                        f"{sample_truncated}; sample_note present in metadata"
                    ),
                    GREEN,
                )
                return "NOT_REPRODUCED"
            status(
                "VERIFIED",
                f"considered={considered} < min(total={total}, max_runs={max_runs})",
                RED,
            )
            return "VERIFIED"
    status(
        "NOT_REPRODUCED",
        f"total={total}, considered={considered}, max_runs={max_runs}",
        GREEN,
    )
    return "NOT_REPRODUCED"


async def case_14_truncation_lie(session: ClientSession) -> str:
    """Reported (v2): truncation flag set with mismatched count.

    `metadata.truncated=true` and `metadata.total_available=N`, but
    `data.patch_policy_schedules` is a list with fewer than N entries.
    """
    _, parsed, raw = await call_tool(session, "get_patch_tuesday_readiness", {})
    if not isinstance(parsed, dict):
        status("AMBIGUOUS", f"unexpected shape — {raw[:200]}", YELLOW)
        return "AMBIGUOUS"
    metadata = parsed.get("metadata") or {}
    data = parsed.get("data") or {}
    total = metadata.get("total_available")
    truncated = metadata.get("truncated")
    schedules = data.get("patch_policy_schedules")
    actual = len(schedules) if isinstance(schedules, list) else None
    # v1.0.23 fix surfaces a per-key truncations map. If
    # truncations[KEY].total == truncations[KEY].returned matches the
    # actual array length, the user has unambiguous per-key counts and
    # the bare `total_available` cross-array sum is no longer the only
    # signal.
    truncations = metadata.get("truncations") or {}
    schedule_trunc = (
        truncations.get("patch_policy_schedules") if isinstance(truncations, dict) else None
    )
    if total is not None and actual is not None and actual < total and truncated:
        if (
            isinstance(schedule_trunc, dict)
            and schedule_trunc.get("total") == total
            and schedule_trunc.get("returned") == actual
        ):
            status(
                "NOT_REPRODUCED",
                (f"per-key truncations map present: patch_policy_schedules={schedule_trunc}"),
                GREEN,
            )
            return "NOT_REPRODUCED"
        status(
            "VERIFIED",
            (
                f"metadata.total_available={total}, array length={actual}, "
                f"metadata.truncated={truncated}"
            ),
            RED,
        )
        return "VERIFIED"
    status(
        "NOT_REPRODUCED",
        f"total_available={total}, array_len={actual}, truncated={truncated}",
        GREEN,
    )
    return "NOT_REPRODUCED"


async def case_57_1_policy_catalog_pagination(session: ClientSession) -> str:
    """Reported (#57.1): policy_catalog page>=3 at limit=10 returned 0 with has_more=true.

    Root cause: the workflow over-fetched `limit*3` from /policies while
    passing the user's `page` directly, so user_page=3 became upstream
    offset=90 instead of 30.

    Verification strategy: ask for the same total population across pages
    1..3 and confirm each page returns distinct, non-empty results when
    the tenant has >30 policies. If page 3 returns 0 policies while
    has_more is true, the cursor is stalled (VERIFIED). Use
    include_stats=true once on page 0 to capture total_available.
    """
    _, p0, _ = await call_tool(
        session, "policy_catalog", {"limit": 10, "page": 0, "include_stats": True}
    )
    if not isinstance(p0, dict):
        status("AMBIGUOUS", "page 0 not a dict", YELLOW)
        return "AMBIGUOUS"
    p0_data = p0.get("data") or {}
    total_available = p0_data.get("total_policies_available")
    if not isinstance(total_available, int) or total_available <= 30:
        status(
            "AMBIGUOUS",
            f"tenant has too few policies to test (total_available={total_available!r})",
            YELLOW,
        )
        return "AMBIGUOUS"

    _, p3, raw3 = await call_tool(session, "policy_catalog", {"limit": 10, "page": 3})
    if not isinstance(p3, dict):
        status("AMBIGUOUS", f"page=3 not a dict — {raw3[:200]}", YELLOW)
        return "AMBIGUOUS"
    p3_data = p3.get("data") or {}
    p3_meta = p3.get("metadata") or {}
    p3_returned = p3_data.get("policies_returned") or 0
    p3_has_more = (p3_meta.get("pagination") or {}).get("has_more")

    # Bug shape: page=3 at limit=10 returns 0 policies but claims has_more=true.
    if p3_returned == 0 and p3_has_more:
        status(
            "VERIFIED",
            (
                f"page=3 limit=10 returned 0 policies but has_more=true "
                f"(total_available={total_available})"
            ),
            RED,
        )
        return "VERIFIED"
    status(
        "NOT_REPRODUCED",
        (
            f"page=3 returned={p3_returned} has_more={p3_has_more} "
            f"total_available={total_available}"
        ),
        GREEN,
    )
    return "NOT_REPRODUCED"


async def case_57_2_policy_runs_v2_filter(session: ClientSession) -> str:
    """Reported (#57.2): policy_runs_v2 silently ignores policy_name and policy_type.

    Both filters accepted by the schema but the upstream call returns
    unfiltered runs (different policy_type than requested, etc.).
    """
    # Use a `policy_type=custom` filter — if filter works, every returned run
    # should have policy_type=custom. If returned runs include other types
    # (e.g. "patch"), the filter was ignored.
    _, parsed, raw = await call_tool(
        session,
        "policy_runs_v2",
        {"policy_type": "custom", "limit": 20},
    )
    if not isinstance(parsed, dict):
        status("AMBIGUOUS", f"unexpected shape — {raw[:200]}", YELLOW)
        return "AMBIGUOUS"
    data = parsed.get("data") or {}
    runs = data.get("runs") or []
    if not isinstance(runs, list) or not runs:
        status("AMBIGUOUS", f"no runs returned — cannot test filter (runs={runs!r})", YELLOW)
        return "AMBIGUOUS"
    types_seen = {r.get("policy_type") for r in runs if isinstance(r, dict)}
    non_custom = types_seen - {"custom"}
    if non_custom:
        status(
            "VERIFIED",
            (
                f"policy_type=custom filter ignored — returned runs include types: "
                f"{sorted(t for t in non_custom if t)} (n={len(runs)})"
            ),
            RED,
        )
        return "VERIFIED"
    status(
        "NOT_REPRODUCED",
        f"all {len(runs)} runs have policy_type=custom — filter honored",
        GREEN,
    )
    return "NOT_REPRODUCED"


async def case_57_3_policy_stats_hides_policies(session: ClientSession) -> str:
    """Reported (#57.3): policy_stats array consumes the token budget and
    truncates the `policies` array, hiding policies that exist in the org.
    """
    _, parsed, raw = await call_tool(session, "policy_catalog", {"limit": 10, "page": 0})
    if not isinstance(parsed, dict):
        status("AMBIGUOUS", f"unexpected shape — {raw[:200]}", YELLOW)
        return "AMBIGUOUS"
    metadata = parsed.get("metadata") or {}
    truncations = metadata.get("truncations") or {}
    policies_trunc = truncations.get("policies") if isinstance(truncations, dict) else None
    stats_trunc = truncations.get("policy_stats") if isinstance(truncations, dict) else None
    # Bug shape: policies array gets truncated below the requested limit
    # because policy_stats consumes most of the budget.
    if isinstance(policies_trunc, dict):
        p_total = policies_trunc.get("total")
        p_returned = policies_trunc.get("returned")
        if isinstance(p_total, int) and isinstance(p_returned, int) and p_returned < p_total:
            status(
                "VERIFIED",
                (
                    f"policies truncated: total={p_total} returned={p_returned}; "
                    f"policy_stats truncation={stats_trunc}"
                ),
                RED,
            )
            return "VERIFIED"
    status(
        "NOT_REPRODUCED",
        f"policies not truncated below request (truncations={truncations})",
        GREEN,
    )
    return "NOT_REPRODUCED"


async def case_5_devices_needing_attention(session: ClientSession) -> str:
    """Reported: returns null for policy_status, pending_patches, last_check_in,
    server_group_id."""
    _, parsed, raw = await call_tool(session, "devices_needing_attention", {})
    if not isinstance(parsed, dict):
        status("AMBIGUOUS", f"unexpected shape — {raw[:200]}", YELLOW)
        return "AMBIGUOUS"
    data = parsed.get("data") or parsed
    devices = data.get("devices") if isinstance(data, dict) else None
    if not devices:
        for key in ("attention", "items", "results"):
            if isinstance(data.get(key), list):
                devices = data[key]
                break
    if not isinstance(devices, list) or not devices:
        status("AMBIGUOUS", "no devices in response", YELLOW)
        return "AMBIGUOUS"
    sample = devices[0]
    diagnostic_fields = ["policy_status", "pending_patches", "last_check_in", "server_group_id"]
    nulls = [f for f in diagnostic_fields if sample.get(f) is None]
    if len(nulls) == len(diagnostic_fields):
        status(
            "VERIFIED",
            f"all diagnostic fields null on first device — keys={list(sample.keys())[:8]}",
            RED,
        )
        return "VERIFIED"
    status(
        "NOT_REPRODUCED",
        f"populated fields present on first device — null fields={nulls}",
        GREEN,
    )
    return "NOT_REPRODUCED"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> int:
    if not os.environ.get("AUTOMOX_API_KEY") or not os.environ.get("AUTOMOX_ACCOUNT_UUID"):
        print("ERROR: AUTOMOX_API_KEY and AUTOMOX_ACCOUNT_UUID must be set", file=sys.stderr)
        return 2

    print(f"{BOLD}Verifying bugs reported against v1.0.20 Claude Desktop session{RESET}")
    print(f"  Org UUID: {ORG_UUID}")
    print(f"  Org ID: {_resolve_org_id()}")
    print(f"  Device ID: {DEVICE_ID}")
    print(f"  Action set ID: {ACTION_SET_ID}")
    print(f"  Policy UUID: {POLICY_UUID}")

    cases = [
        (1, "get_patch_tuesday_readiness → 500", case_1_patch_tuesday),
        (2, "get_action_set_actions → 405", case_2_action_set_actions),
        (3, "policy_run_detail_v2 → 400 (org=null)", case_3_policy_run_detail_v2),
        (4, "get_action_set_detail no-op", case_4a_action_set_detail_noop),
        (4, "policy_history_detail no run history", case_4b_policy_history_detail_noop),
        (5, "devices_needing_attention all-null fields", case_5_devices_needing_attention),
        (6, "get_device_assignments Spring leak", case_6_device_assignments_spring_leak),
        (7, "policy_run_results filter ignored", case_7_policy_run_results_filter),
        (8, "audit actor cursor advance on miss", case_8_audit_actor_cursor),
        (9, "policy_health_overview sample mismatch", case_9_policy_health_sample),
        (14, "patch_tuesday truncation lie (total_available != array)", case_14_truncation_lie),
        (57, "policy_catalog pagination past page 2 (#57.1)", case_57_1_policy_catalog_pagination),
        (57, "policy_runs_v2 filter ignored (#57.2)", case_57_2_policy_runs_v2_filter),
        (
            57,
            "policy_stats hides policies via truncation (#57.3)",
            case_57_3_policy_stats_hides_policies,
        ),
    ]

    results: list[tuple[int, str, str]] = []
    async with open_session() as session:
        for num, name, fn in cases:
            case(num, name)
            try:
                result = await fn(session)
            except Exception as exc:  # noqa: BLE001
                status("ERROR", f"{type(exc).__name__}: {exc}", RED)
                result = "ERROR"
            results.append((num, name, result))

    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}Summary{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")
    counts: dict[str, int] = {}
    color_map = {"VERIFIED": RED, "NOT_REPRODUCED": GREEN, "AMBIGUOUS": YELLOW, "ERROR": RED}
    for num, name, result in results:
        counts[result] = counts.get(result, 0) + 1
        color = color_map.get(result, "")
        print(f"  #{num} {name}: {color}{result}{RESET}")

    totals = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"\n  Totals: {totals}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

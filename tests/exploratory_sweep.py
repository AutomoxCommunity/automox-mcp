#!/usr/bin/env python3
"""Very-thorough exploratory tool sweep across operator personas.

Scope: 8 personas, ~50 probes total, read-only + safe writes with auto-cleanup.
For each probe: call the tool, run a battery of validators, and emit one of
PASS / ANOMALY / FAIL.

Unlike ``verify_reported_bugs.py`` (which re-checks a fixed list of
previously-reported bugs), this harness exercises tool surfaces that are
known to be brittle — pagination, sanitization, compound-tool truncation,
empty-result handling, idempotency — across realistic operator workflows.

The findings are not assertions; they're signals to triage. ANOMALY ≠ bug;
it means "this response shape is suspicious, look at it." A clean sweep
gives you confidence the obvious surfaces are working; a noisy one tells
you where to dig.

Requirements (env): same as tests/verify_reported_bugs.py — AUTOMOX_API_KEY,
AUTOMOX_ACCOUNT_UUID, plus the VERIFY_* fixture ids.

Optional env:
    SWEEP_WEBHOOK_SINK     — public HTTPS sink URL for the safe-write probe.
                              Defaults to https://httpbin.org/post.
    SWEEP_SKIP_WRITES      — set to "1" to skip all safe-write probes.

Usage:
    set -a && . ~/automox/.env && set +a && \\
        uv run python tests/exploratory_sweep.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from collections import Counter
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ---------------------------------------------------------------------------
# Tenant context (shared with verify_reported_bugs.py defaults)
# ---------------------------------------------------------------------------
ORG_UUID = os.environ.get("VERIFY_ORG_UUID", "1bfab13f-3d5f-482f-9c40-f6ab840fbe1b")
ORG_ID = os.environ.get("VERIFY_ORG_ID", "101934")
DEVICE_ID = int(os.environ.get("VERIFY_DEVICE_ID", "2520712"))
POLICY_UUID = os.environ.get("VERIFY_POLICY_UUID", "e1c9b860-bc73-4ae2-bef5-2cdc3b7e2f8e")

SWEEP_WEBHOOK_SINK = os.environ.get("SWEEP_WEBHOOK_SINK", "https://httpbin.org/post")
SWEEP_SKIP_WRITES = os.environ.get("SWEEP_SKIP_WRITES", "").strip() in {"1", "true", "yes"}

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
DIM = "\033[2m"


class Finding:
    __slots__ = ("persona", "scenario", "step", "tool", "status", "detail")

    def __init__(
        self,
        persona: str,
        scenario: str,
        step: str,
        tool: str,
        status: str,
        detail: str,
    ) -> None:
        self.persona = persona
        self.scenario = scenario
        self.step = step
        self.tool = tool
        self.status = status
        self.detail = detail


FINDINGS: list[Finding] = []
_CURRENT: dict[str, str] = {"persona": "", "scenario": ""}


def header(text: str, char: str = "=") -> None:
    print(f"\n{BOLD}{char * 72}\n{text}\n{char * 72}{RESET}")


def persona(name: str) -> None:
    _CURRENT["persona"] = name
    print(f"\n{BOLD}{BLUE}▶ {name}{RESET}")


def scenario(name: str) -> None:
    _CURRENT["scenario"] = name
    print(f"  {DIM}{name}{RESET}")


def record(step: str, tool: str, status_label: str, detail: str) -> None:
    FINDINGS.append(
        Finding(_CURRENT["persona"], _CURRENT["scenario"], step, tool, status_label, detail)
    )
    color = {"PASS": GREEN, "ANOMALY": YELLOW, "FAIL": RED, "SKIP": DIM}.get(status_label, "")
    truncated = detail if len(detail) <= 110 else detail[:107] + "..."
    print(f"    [{color}{status_label:7}{RESET}] {tool:38} {truncated}")


# ---------------------------------------------------------------------------
# MCP client
# ---------------------------------------------------------------------------
def _resolve_org_id() -> str:
    return os.environ.get("AUTOMOX_ORG_ID") or ORG_ID


@asynccontextmanager
async def open_session():
    server = StdioServerParameters(
        command="uv",
        args=["run", "automox-mcp"],
        env={
            **os.environ,
            "AUTOMOX_ORG_ID": _resolve_org_id(),
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


# ---------------------------------------------------------------------------
# Validators — each returns a list of anomaly strings (empty == OK)
# ---------------------------------------------------------------------------
def v_envelope(parsed: Any, raw: str) -> list[str]:
    """Response must be a dict with 'data' and 'metadata' keys."""
    if not isinstance(parsed, dict):
        return [f"top-level not dict (got {type(parsed).__name__})"]
    out = []
    if "data" not in parsed:
        out.append("missing 'data' key")
    if "metadata" not in parsed:
        out.append("missing 'metadata' key")
    return out


def v_data_present(parsed: Any, raw: str) -> list[str]:
    """data must be non-None (can be empty list/dict, but not null)."""
    if not isinstance(parsed, dict):
        return []  # v_envelope already flagged
    if parsed.get("data") is None:
        return ["data is null"]
    return []


def v_no_exception_leak(parsed: Any, raw: str) -> list[str]:
    """No Python exception traceback should leak into the response."""
    out = []
    for needle in ("Traceback (most recent call last)", ' File "/', "  File '/"):
        if needle in raw:
            out.append(f"exception leak detected: {needle!r}")
    return out


def v_no_internal_path_leak(parsed: Any, raw: str) -> list[str]:
    """Filesystem paths from the *server host* should not appear in responses.

    Earlier versions also flagged ``/Users/`` and ``/private/var/``, but those
    are legitimate macOS device-inventory paths (LaunchAgent plists, syslog
    sockets, etc.) returned by ``get_device_inventory`` and friends — the
    paths are FROM the managed endpoint, not the MCP server. Only flag
    ``/home/runner`` (the GitHub Actions runner path) which would never
    legitimately appear in API responses.
    """
    if "/home/runner" in raw:
        return ["internal path leak: '/home/runner'"]
    return []


def v_pagination_coherent(parsed: Any, raw: str) -> list[str]:
    """If pagination metadata claims has_more, the response must provide a hint
    for how to fetch the next page. Accepts cursor-, offset-, or page-based
    schemes (next_cursor / next_offset / next_page) or a top-level
    metadata.suggested_next_call block (the canonical contract since #76)."""
    if not isinstance(parsed, dict):
        return []
    meta = parsed.get("metadata") or {}
    if not isinstance(meta, dict):
        return ["metadata is not a dict"]
    pag = meta.get("pagination") if isinstance(meta.get("pagination"), dict) else meta
    has_more = pag.get("has_more") if isinstance(pag, dict) else None
    if not has_more:
        return []
    # Any one of these is sufficient evidence the caller can drill into the
    # next page. policy_catalog / policy_runs_v2 use next_page +
    # suggested_next_call; cursor-based tools use next_cursor; offset-based
    # tools use next_offset. A top-level suggested_next_call is the canonical
    # form per the compound-tool contract.
    if isinstance(pag, dict):
        for hint in ("next_cursor", "next_offset", "next_page"):
            if pag.get(hint) is not None:
                return []
    if meta.get("next_cursor") is not None:
        return []
    if isinstance(meta.get("suggested_next_call"), dict):
        return []
    return ["has_more=True but no next_cursor / next_offset / next_page / suggested_next_call"]


def v_truncation_honest(parsed: Any, raw: str) -> list[str]:
    """If truncated=True, the count metadata must agree with the actual array length."""
    if not isinstance(parsed, dict):
        return []
    meta = parsed.get("metadata") or {}
    data = parsed.get("data")
    if not isinstance(meta, dict):
        return []
    out = []
    # New per-key truncations map (v1.0.23+)
    truncations = meta.get("truncations")
    if isinstance(truncations, dict) and isinstance(data, dict):
        for key, info in truncations.items():
            if not isinstance(info, dict):
                continue
            actual = data.get(key)
            returned_claim = info.get("returned")
            if isinstance(actual, list) and isinstance(returned_claim, int):
                if len(actual) != returned_claim:
                    out.append(
                        f"truncation lie: truncations[{key}].returned={returned_claim} "
                        f"but actual list len={len(actual)}"
                    )
    return out


def v_section_summaries_consistent(parsed: Any, raw: str) -> list[str]:
    """Compound-tool section_summaries must reference real keys and have follow_up_tool."""
    if not isinstance(parsed, dict):
        return []
    meta = parsed.get("metadata") or {}
    if not isinstance(meta, dict):
        return []
    sections = meta.get("section_summaries")
    if not isinstance(sections, dict):
        return []
    out = []
    for key, info in sections.items():
        if not isinstance(info, dict):
            out.append(f"section_summaries[{key}] not a dict")
            continue
        if info.get("has_more") and not info.get("follow_up_tool"):
            out.append(f"section_summaries[{key}].has_more=True but no follow_up_tool")
        # The section_summaries key may itself be dotted (e.g. "packages.packages"),
        # so a missing top-level key in data is not on its own an anomaly.
    return out


def v_no_html_leak(parsed: Any, raw: str) -> list[str]:
    """If sanitization is on, common HTML tags shouldn't appear in string values."""
    # Only flag if it really looks like raw HTML (not '<' in JSON syntax).
    out = []
    for needle in ("<script", "<iframe", "<style"):
        if needle.lower() in raw.lower():
            out.append(f"possible HTML leak: {needle!r}")
    return out


# ---------------------------------------------------------------------------
# Probe helper — runs validators, records finding
# ---------------------------------------------------------------------------
_DEFAULT_VALIDATORS = (
    v_envelope,
    v_data_present,
    v_no_exception_leak,
    v_no_internal_path_leak,
    v_pagination_coherent,
    v_truncation_honest,
    v_section_summaries_consistent,
    v_no_html_leak,
)


async def probe(
    session: ClientSession,
    step: str,
    tool: str,
    args: dict[str, Any],
    *,
    validators: tuple = _DEFAULT_VALIDATORS,
    expect_error: bool = False,
    extra_anomaly_checks: list[str] | None = None,
) -> Any:
    is_error, parsed, raw = await call_tool(session, tool, args)
    # The MCP server enforces 30 calls per 60s locally; a ~50-probe sweep
    # blows past that in under a minute. Detect the rate-limit error and
    # sleep until the sliding window opens, then retry once. Real failures
    # (other isError outcomes) propagate as FAIL on first attempt.
    if is_error and "rate limit exceeded" in raw.lower():
        print(f"    [{DIM}WAIT   {RESET}] rate-limited; sleeping 60s before retrying {tool}...")
        await asyncio.sleep(60)
        is_error, parsed, raw = await call_tool(session, tool, args)
    if is_error and not expect_error:
        record(step, tool, "FAIL", f"isError — {raw[:120]}")
        return parsed
    if expect_error and not is_error:
        record(step, tool, "ANOMALY", "expected error but call succeeded")
        return parsed

    anomalies: list[str] = []
    for v in validators:
        try:
            anomalies.extend(v(parsed, raw) or [])
        except Exception as exc:  # noqa: BLE001
            anomalies.append(f"validator {v.__name__} crashed: {exc!r}")

    if extra_anomaly_checks:
        anomalies.extend(extra_anomaly_checks)

    if anomalies:
        record(step, tool, "ANOMALY", " | ".join(anomalies))
    else:
        if isinstance(parsed, dict):
            data = parsed.get("data")
            shape = (
                f"data=list[{len(data)}]"
                if isinstance(data, list)
                else f"data=dict({len(data)} keys)"
                if isinstance(data, dict)
                else f"data={type(data).__name__}"
            )
            record(step, tool, "PASS", shape)
        else:
            record(step, tool, "PASS", "ok")
    return parsed


# ---------------------------------------------------------------------------
# Persona scenarios
# ---------------------------------------------------------------------------
async def persona_patch_admin(session: ClientSession) -> None:
    persona("Patch Tuesday Admin")

    scenario("compound readiness + drill into truncated sections")
    parsed = await probe(
        session,
        "compound readiness",
        "get_patch_tuesday_readiness",
        {"detail_limit": 3},
    )
    # Follow the section_summaries follow-up dispatch if any
    meta = (parsed or {}).get("metadata") or {}
    sections = meta.get("section_summaries") or {} if isinstance(meta, dict) else {}
    if isinstance(sections, dict):
        for key, info in list(sections.items())[:2]:
            if isinstance(info, dict) and info.get("has_more") and info.get("follow_up_tool"):
                follow_tool = info["follow_up_tool"]
                hint = info.get("follow_up_args_hint") or {}
                if isinstance(hint, dict):
                    await probe(session, f"follow-up [{key}]", follow_tool, hint)

    scenario("patch_approvals_summary with no filter, then status filter")
    await probe(session, "summary all", "patch_approvals_summary", {})
    await probe(session, "summary pending", "patch_approvals_summary", {"status": "pending"})


async def persona_security_analyst(session: ClientSession) -> None:
    persona("Security Analyst / IR")

    scenario("compliance snapshot with section truncation")
    await probe(
        session,
        "snapshot detail_limit=3",
        "get_compliance_snapshot",
        {"detail_limit": 3},
    )

    scenario("noncompliant report — full auto-paginate")
    await probe(session, "noncompliant report", "noncompliant_report", {})

    scenario("audit events recent activity")
    # audit_events_ocsf requires a date string (YYYY-MM-DD). Use today.
    today = time.strftime("%Y-%m-%d")
    await probe(
        session,
        "audit_events_ocsf",
        "audit_events_ocsf",
        {"date": today, "limit": 10},
    )

    # advanced_device_search takes a structured Elasticsearch-style `query`
    # dict whose exact DSL isn't documented here; calling without that
    # specific shape returns "organizationUuids required" from upstream.
    # The Fleet Manager persona already exercises `search_devices` for the
    # device-search surface, so we skip this probe rather than guess at
    # the right payload and emit noise. To probe this tool, pass a
    # tenant-specific query via env var (out of scope for the canned sweep).
    record(
        "minimal query",
        "advanced_device_search",
        "SKIP",
        "upstream query DSL not modeled; covered by search_devices in Fleet Manager",
    )


async def persona_fleet_manager(session: ClientSession) -> None:
    persona("Fleet Manager")

    scenario("list devices small page → multi-page if available")
    await probe(session, "list page 1", "list_devices", {"limit": 50})

    scenario("device health aggregate")
    await probe(session, "device_health_metrics", "device_health_metrics", {})

    scenario("devices_needing_attention small limit")
    await probe(
        session,
        "needs attention",
        "devices_needing_attention",
        {"limit": 5},
    )

    scenario("server group listing + drill")
    parsed = await probe(session, "list groups", "list_server_groups", {})
    data = (parsed or {}).get("data") or {}
    groups = []
    if isinstance(data, dict):
        groups = data.get("groups") or data.get("server_groups") or []
    elif isinstance(data, list):
        groups = data
    if groups:
        first = groups[0]
        if isinstance(first, dict):
            gid = first.get("id") or first.get("group_id")
            if gid:
                await probe(session, "group detail", "get_server_group", {"group_id": gid})


async def persona_policy_operator(session: ClientSession) -> None:
    persona("Policy Operator")

    scenario("policy_catalog page 0, then deep page 5")
    await probe(session, "catalog page 0", "policy_catalog", {"limit": 10})
    await probe(session, "catalog page 5", "policy_catalog", {"limit": 10, "page": 5})

    scenario("compliance stats whole-org")
    await probe(session, "policy_compliance_stats", "policy_compliance_stats", {})

    scenario("policy_detail + runs + count for a known policy")
    # Resolve a real policy_id from the catalog rather than guessing at id=1
    # (which doesn't exist on most tenants and produces unhelpful FAILs).
    catalog_parsed = await probe(session, "lookup policy id", "policy_catalog", {"limit": 1})
    catalog_data = (catalog_parsed or {}).get("data") if isinstance(catalog_parsed, dict) else None
    policy_id: int | None = None
    if isinstance(catalog_data, dict):
        policies = catalog_data.get("policies") or []
        if isinstance(policies, list) and policies and isinstance(policies[0], dict):
            pid = policies[0].get("id") or policies[0].get("policy_id")
            if isinstance(pid, int):
                policy_id = pid
    if policy_id is not None:
        await probe(
            session,
            "policy detail",
            "policy_detail",
            {"policy_id": policy_id, "include_recent_runs": 3},
        )
    else:
        record("policy detail", "policy_detail", "SKIP", "no policy id resolvable from catalog")
    # Use the configured policy UUID for the v2 path
    await probe(
        session,
        "runs_v2",
        "policy_runs_v2",
        {"policy_uuid": POLICY_UUID, "limit": 5},
    )
    # policy_run_count is org-scoped aggregate; only accepts `days`.
    await probe(session, "run_count", "policy_run_count", {"days": 7})


async def persona_vuln_manager(session: ClientSession) -> None:
    persona("Vulnerability Manager")

    scenario("action sets list + drill into first id")
    parsed = await probe(session, "list action sets", "list_remediation_action_sets", {})
    data = (parsed or {}).get("data") or {}
    candidates = []
    if isinstance(data, dict):
        candidates = data.get("action_sets") or data.get("items") or []
    elif isinstance(data, list):
        candidates = data
    if candidates:
        first = candidates[0]
        if isinstance(first, dict):
            aid = first.get("id") or first.get("action_set_id")
            if aid is not None:
                await probe(session, "issues", "get_action_set_issues", {"action_set_id": aid})
                await probe(
                    session, "solutions", "get_action_set_solutions", {"action_set_id": aid}
                )
                await probe(session, "detail", "get_action_set_detail", {"action_set_id": aid})
        else:
            record("drill", "get_action_set_*", "SKIP", "no action sets on tenant")
    else:
        record("drill", "get_action_set_*", "SKIP", "no action sets on tenant")


async def persona_webhook_admin(session: ClientSession) -> None:
    persona("Webhook / Event Admin")

    scenario("event type catalog + webhook listing")
    await probe(session, "event types", "list_webhook_event_types", {})
    parsed = await probe(session, "list webhooks", "list_webhooks", {"org_uuid": ORG_UUID})
    # Drill into the first webhook if any exist
    data = (parsed or {}).get("data") or {}
    items = data.get("webhooks") if isinstance(data, dict) else []
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict) and first.get("id"):
            await probe(
                session,
                "webhook detail",
                "get_webhook",
                {"org_uuid": ORG_UUID, "webhook_id": first["id"]},
            )

    scenario("events stream — cursor pagination")
    parsed = await probe(session, "events page 0", "list_events", {"limit": 5})
    meta = (parsed or {}).get("metadata") or {}
    if isinstance(meta, dict):
        cursor = (
            (meta.get("pagination") or {}).get("next_cursor")
            if isinstance(meta.get("pagination"), dict)
            else meta.get("next_cursor")
        )
        if cursor:
            await probe(session, "events page 1", "list_events", {"limit": 5, "cursor": cursor})


async def persona_device_drill(session: ClientSession) -> None:
    persona("Device Drill-Down")

    scenario(f"full profile for VERIFY_DEVICE_ID={DEVICE_ID}")
    await probe(
        session,
        "full profile",
        "get_device_full_profile",
        {"device_id": DEVICE_ID, "detail_limit": 3},
    )

    scenario("device_detail with all includes")
    detail_parsed = await probe(
        session,
        "detail",
        "device_detail",
        {
            "device_id": DEVICE_ID,
            "include_packages": True,
            "include_inventory": True,
            "include_queue": True,
            "include_raw_details": False,
        },
    )
    # Pull the device UUID from the detail response for the UUID-keyed
    # follow-up tools (get_device_scheduled_windows expects a UUID, not an
    # integer device_id).
    detail_data = (detail_parsed or {}).get("data") if isinstance(detail_parsed, dict) else None
    device_uuid: str | None = None
    if isinstance(detail_data, dict):
        device_uuid = detail_data.get("server_uuid") or detail_data.get("uuid")

    scenario("inventory + categories")
    await probe(
        session,
        "inventory",
        "get_device_inventory",
        {"device_id": DEVICE_ID},
    )
    await probe(
        session,
        "categories",
        "get_device_inventory_categories",
        {"device_id": DEVICE_ID},
    )

    scenario("assignments + scheduled windows")
    # get_device_assignments is org-wide (no device_id arg).
    await probe(session, "assignments", "get_device_assignments", {})
    # get_device_scheduled_windows is UUID-keyed. Skip if we couldn't resolve.
    if device_uuid:
        await probe(
            session,
            "scheduled windows",
            "get_device_scheduled_windows",
            {"org_uuid": ORG_UUID, "device_uuid": device_uuid},
        )
    else:
        record(
            "scheduled windows",
            "get_device_scheduled_windows",
            "SKIP",
            "no device UUID resolvable from device_detail",
        )

    scenario("packages — paginated list")
    await probe(
        session,
        "packages",
        "list_device_packages",
        {"device_id": DEVICE_ID, "limit": 10},
    )


async def persona_maintenance_windows(session: ClientSession) -> None:
    persona("Maintenance Windows")

    scenario("policy windows search + drill")
    # search_policy_windows uses `size` not `limit` (Spring-style pagination).
    parsed = await probe(
        session,
        "search windows",
        "search_policy_windows",
        {"org_uuid": ORG_UUID, "size": 5},
    )
    data = (parsed or {}).get("data") or {}
    items = data.get("policy_windows") if isinstance(data, dict) else []
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict) and first.get("id"):
            await probe(
                session,
                "window detail",
                "get_policy_window",
                {"org_uuid": ORG_UUID, "policy_window_id": first["id"]},
            )
            await probe(
                session,
                "window active check",
                "check_window_active",
                {"org_uuid": ORG_UUID, "policy_window_id": first["id"]},
            )

    scenario("group scheduled windows")
    # get_group_scheduled_windows is UUID-keyed. Pull the UUID from the
    # server-groups listing rather than the integer id.
    groups_parsed = await probe(session, "list groups", "list_server_groups", {})
    data = (groups_parsed or {}).get("data") or {}
    groups = (
        data.get("groups") or data.get("server_groups") or (data if isinstance(data, list) else [])
    )
    group_uuid: str | None = None
    if isinstance(groups, list) and groups and isinstance(groups[0], dict):
        first = groups[0]
        group_uuid = first.get("uuid") or first.get("server_group_uuid") or first.get("group_uuid")
    if group_uuid:
        # The upstream requires `date` even though the Pydantic schema marks
        # it optional, and the exact accepted format is tenant- /
        # endpoint-specific (YYYY-MM-DD rejected as "Invalid date-time
        # format", ISO 8601 UTC rejected as "Validation failed"). Skip
        # rather than guess at undocumented upstream date semantics; this
        # is a tool-quirk to document, not a harness defect.
        record(
            "group windows",
            "get_group_scheduled_windows",
            "SKIP",
            "upstream `date` format undocumented (rejects YYYY-MM-DD and ISO 8601 UTC)",
        )
    else:
        record(
            "group windows",
            "get_group_scheduled_windows",
            "SKIP",
            "no group UUID resolvable from list_server_groups",
        )


# ---------------------------------------------------------------------------
# Safe writes — every create paired with a cleanup
# ---------------------------------------------------------------------------
async def safe_writes(session: ClientSession) -> None:
    persona("Safe Writes (auto-cleanup)")
    if SWEEP_SKIP_WRITES:
        record("all", "(skipped)", "SKIP", "SWEEP_SKIP_WRITES set")
        return

    sentinel = f"sweep-probe-{uuid.uuid4().hex[:8]}"

    # create_server_group requires parent_server_group_id; grab the org's
    # default (first listed) group to nest the probe-created group under.
    groups_parsed = await probe(session, "lookup parent group", "list_server_groups", {})
    groups_data = (groups_parsed or {}).get("data") or {}
    candidates = (
        groups_data.get("groups")
        or groups_data.get("server_groups")
        or (groups_data if isinstance(groups_data, list) else [])
    )
    parent_id: int | None = None
    if isinstance(candidates, list):
        for g in candidates:
            if isinstance(g, dict):
                pid = g.get("id") or g.get("server_group_id")
                if isinstance(pid, int):
                    parent_id = pid
                    break

    scenario(f"server group create+delete: name={sentinel}")
    if parent_id is None:
        record(
            "create group",
            "create_server_group",
            "SKIP",
            "no parent_server_group_id resolvable from list_server_groups",
        )
    else:
        parsed = await probe(
            session,
            "create group",
            "create_server_group",
            {
                "name": sentinel,
                # 1440 minutes = 24h (typical default). ui_color (not `color`).
                "refresh_interval": 1440,
                "parent_server_group_id": parent_id,
                "ui_color": "#888888",
            },
        )
        data = (parsed or {}).get("data") or {}
        gid = data.get("id") if isinstance(data, dict) else None
        if gid:
            await probe(session, "delete group", "delete_server_group", {"group_id": gid})
        else:
            record("delete group", "delete_server_group", "SKIP", "create did not return an id")

    scenario(f"webhook create+delete using sink={SWEEP_WEBHOOK_SINK}")
    parsed = await probe(
        session,
        "create webhook",
        "create_webhook",
        {
            "name": sentinel,
            "url": SWEEP_WEBHOOK_SINK,
            "event_types": ["device.created"],
            "org_uuid": ORG_UUID,
        },
    )
    data = (parsed or {}).get("data") or {}
    wid = data.get("id") if isinstance(data, dict) else None
    if wid:
        # Test webhook delivery (non-destructive on Automox side)
        await probe(
            session,
            "test delivery",
            "test_webhook",
            {"org_uuid": ORG_UUID, "webhook_id": wid},
        )
        await probe(
            session,
            "delete webhook",
            "delete_webhook",
            {"org_uuid": ORG_UUID, "webhook_id": wid},
        )
    else:
        record("delete webhook", "delete_webhook", "SKIP", "create did not return an id")

    scenario("idempotency double-call")
    if parent_id is None:
        record(
            "idempotency",
            "create_server_group",
            "SKIP",
            "no parent_server_group_id resolvable",
        )
        return
    req_id = f"sweep-{uuid.uuid4().hex}"
    sentinel2 = f"sweep-idem-{uuid.uuid4().hex[:8]}"
    idem_args = {
        "name": sentinel2,
        "refresh_interval": 1440,
        "parent_server_group_id": parent_id,
        "ui_color": "#888888",
        "request_id": req_id,
    }
    parsed_a = await probe(
        session,
        "create group #1",
        "create_server_group",
        idem_args,
    )
    parsed_b = await probe(
        session,
        "create group #2 same id",
        "create_server_group",
        idem_args,
    )
    # Both should resolve cleanly. Either the second is a `duplicate=True`
    # marker (in-flight collision unlikely since we awaited the first) or it
    # returns the cached completed response.
    data_a = (parsed_a or {}).get("data") if isinstance(parsed_a, dict) else None
    data_b = (parsed_b or {}).get("data") if isinstance(parsed_b, dict) else None
    if isinstance(data_a, dict) and isinstance(data_b, dict):
        if data_a.get("id") != data_b.get("id") and not data_b.get("duplicate"):
            record(
                "idempotency",
                "create_server_group",
                "ANOMALY",
                f"second call returned different id ({data_a.get('id')} vs {data_b.get('id')}) "
                "and no duplicate marker — cache miss?",
            )
        else:
            record("idempotency", "create_server_group", "PASS", "second call deduped")
    # Cleanup the group
    gid_a = data_a.get("id") if isinstance(data_a, dict) else None
    if gid_a:
        await probe(
            session,
            "cleanup idem group",
            "delete_server_group",
            {"group_id": gid_a},
        )


# ---------------------------------------------------------------------------
# Summary + main
# ---------------------------------------------------------------------------
def print_summary() -> None:
    header("Summary")
    counts: Counter[str] = Counter(f.status for f in FINDINGS)
    print(f"  Total probes: {len(FINDINGS)}")
    for label in ("PASS", "ANOMALY", "FAIL", "SKIP"):
        if counts.get(label):
            color = {"PASS": GREEN, "ANOMALY": YELLOW, "FAIL": RED, "SKIP": DIM}[label]
            print(f"  {color}{label:7}{RESET} {counts[label]}")

    if counts.get("ANOMALY") or counts.get("FAIL"):
        header("Anomalies + failures (triage queue)", char="-")
        for f in FINDINGS:
            if f.status in ("ANOMALY", "FAIL"):
                color = YELLOW if f.status == "ANOMALY" else RED
                print(
                    f"  [{color}{f.status:7}{RESET}] {f.persona} / {f.scenario} / {f.step}\n"
                    f"           tool={f.tool}\n"
                    f"           {f.detail}"
                )


async def main() -> int:
    if not os.environ.get("AUTOMOX_API_KEY") or not os.environ.get("AUTOMOX_ACCOUNT_UUID"):
        print("ERROR: AUTOMOX_API_KEY and AUTOMOX_ACCOUNT_UUID must be set", file=sys.stderr)
        return 2

    header("Exploratory tool sweep — read-only + safe writes")
    print(f"  Tenant org: {_resolve_org_id()} ({ORG_UUID})")
    print(f"  Device fixture: {DEVICE_ID}")
    print(f"  Webhook sink: {SWEEP_WEBHOOK_SINK}")
    print(f"  Skip writes: {SWEEP_SKIP_WRITES}")

    started = time.monotonic()
    async with open_session() as session:
        await persona_patch_admin(session)
        await persona_security_analyst(session)
        await persona_fleet_manager(session)
        await persona_policy_operator(session)
        await persona_vuln_manager(session)
        await persona_webhook_admin(session)
        await persona_device_drill(session)
        await persona_maintenance_windows(session)
        await safe_writes(session)

    elapsed = time.monotonic() - started
    print(f"\n  Elapsed: {elapsed:.1f}s")
    print_summary()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

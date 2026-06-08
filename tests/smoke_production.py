#!/usr/bin/env python3
"""Production smoke tests for the Automox MCP server.

Exercises startup, HTTP transport, correlation IDs, idempotency, markdown
output, capability discovery, non-loopback warnings, and every read-only
tool against a live Automox organisation.  Tests 35–49 cover Phase 3 tools
(worklets, data extracts, org API keys, policy history v2, audit v2/OCSF,
advanced device search, and vulnerability sync).  Tests 50–55 cover policy
windows (maintenance/exclusion windows).  Tests 56–91 cover the 1.2.0 #91
wave (identity/users/zones, API-key metadata, device-search enrichment,
policy device-targeting, action-set detail, Splashtop read-only status) plus
the #111 single-device update_device (re-applied as a no-op write). Test 92
verifies the MCP App ``ui://`` resources (#178–#182) boot and list with the
MCP-App MIME over a live server, and ``list_zone_users`` asserts its
secret-stripping projection holds against the live payload (no ``intercom_hmac``
/ ``access_key`` leak, #194). The output_schema-bearing tools (compound, report,
``patch_approvals_summary``, ``get_action_set_solutions``, ``list_users``) are
live schema-conformance checks for free: the server validates each return
against its advertised ``output_schema`` and a mismatch surfaces as a tool error
(recorded FAIL).

Dependent reads chain IDs from their list call and skip-OK when the org has
no such record, so a sparse tenant does not fail the run.

Note: The idempotency test issues an ``execute_device_command`` call with
``command_type="scan"`` against a real device.  This queues a lightweight
GetOS scan and is therefore a *write* operation, though it is idempotent
(repeated calls with the same ``request_id`` return a cached response).

Requirements:
    AUTOMOX_API_KEY, AUTOMOX_ACCOUNT_UUID, and AUTOMOX_ORG_ID must be set.

Usage:
    uv run python tests/smoke_production.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

# ---------------------------------------------------------------------------
# MCP client imports (provided by the `mcp` package)
# ---------------------------------------------------------------------------
from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client

# ---------------------------------------------------------------------------
# Optional .env loading
# ---------------------------------------------------------------------------
try:
    # Check common .env locations
    from pathlib import Path

    from dotenv import load_dotenv

    for env_path in [
        Path.cwd() / ".env",
        Path.home() / "automox" / ".env",
    ]:
        if env_path.is_file():
            load_dotenv(env_path)
            break
except ImportError:
    # python-dotenv is optional; env vars can be supplied directly in the shell.
    pass

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("smoke")

# Silence noisy HTTP request logs from httpx/httpcore
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("mcp.client").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Colour helpers (ANSI)
# ---------------------------------------------------------------------------
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

# ---------------------------------------------------------------------------
# Bookkeeping
# ---------------------------------------------------------------------------
_results: list[tuple[str, bool, str]] = []  # (name, passed, detail)

SERVER_PORT = 18321
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}/mcp"

# ---------------------------------------------------------------------------
# Prereqs
# ---------------------------------------------------------------------------
REQUIRED_ENV = ("AUTOMOX_API_KEY", "AUTOMOX_ACCOUNT_UUID", "AUTOMOX_ORG_ID")

# Resolve the automox-mcp console script in the venv
_AUTOMOX_MCP_BIN = shutil.which("automox-mcp") or os.path.join(
    os.path.dirname(sys.executable), "automox-mcp"
)


def _server_cmd() -> list[str]:
    """Return the base command to invoke automox-mcp."""
    if os.path.isfile(_AUTOMOX_MCP_BIN):
        return [_AUTOMOX_MCP_BIN]
    # Fallback: use uv run
    return ["uv", "run", "automox-mcp"]


def check_prereqs() -> None:
    missing = [v for v in REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        sys.exit(f"Missing environment variables: {', '.join(missing)}")


# ---------------------------------------------------------------------------
# Test result helpers
# ---------------------------------------------------------------------------


def record(name: str, passed: bool, detail: str = "") -> None:
    tag = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
    log.info(f"  [{tag}] {name}" + (f" — {detail}" if detail else ""))
    _results.append((name, passed, detail))


def summary() -> int:
    total = len(_results)
    passed = sum(1 for _, p, _ in _results if p)
    failed = total - passed
    log.info("")
    log.info(f"{BOLD}{'=' * 60}{RESET}")
    log.info(
        f"  {BOLD}{total} tests{RESET}:  "
        f"{GREEN}{passed} passed{RESET},  "
        f"{RED}{failed} failed{RESET}"
    )
    if failed:
        log.info(f"\n  {RED}Failed tests:{RESET}")
        for name, p, detail in _results:
            if not p:
                log.info(f"    - {name}: {detail}")
    log.info(f"{BOLD}{'=' * 60}{RESET}")
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# Server lifecycle helpers
# ---------------------------------------------------------------------------


def start_server(
    *extra_args: str,
    port: int = SERVER_PORT,
    capture_stderr: bool = False,
) -> subprocess.Popen:
    """Start the MCP server as a background process."""
    cmd = [
        *_server_cmd(),
        "--transport",
        "http",
        "--port",
        str(port),
        "--no-banner",
        *extra_args,
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture_stderr else subprocess.DEVNULL,
    )
    # Give uvicorn time to bind
    time.sleep(4)
    if proc.poll() is not None:
        stderr_out = ""
        if capture_stderr and proc.stderr:
            stderr_out = proc.stderr.read().decode(errors="replace")
        raise RuntimeError(
            f"Server exited immediately (rc={proc.returncode}). stderr: {stderr_out}"
        )
    return proc


def stop_server(proc: subprocess.Popen) -> str:
    """Stop the server, return captured stderr."""
    stderr_text = ""
    proc.send_signal(signal.SIGTERM)
    try:
        _, stderr_bytes = proc.communicate(timeout=5)
        if stderr_bytes:
            stderr_text = stderr_bytes.decode(errors="replace")
    except subprocess.TimeoutExpired:
        proc.kill()
        _, stderr_bytes = proc.communicate(timeout=3)
        if stderr_bytes:
            stderr_text = stderr_bytes.decode(errors="replace")
    return stderr_text


@asynccontextmanager
async def mcp_session(url: str = SERVER_URL):
    """Open an MCP ClientSession over streamable HTTP."""
    async with streamablehttp_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


# ---------------------------------------------------------------------------
# Helper: call a tool and return parsed inner JSON
# ---------------------------------------------------------------------------


async def call_tool(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call an MCP tool and return the parsed JSON from the first text content."""
    result = await session.call_tool(name, arguments=arguments or {})
    return _parse_tool_result(result)


# ===================================================================
#  TESTS
# ===================================================================

# ---------------------------------------------------------------------------
# 1. Basic smoke test — stdio startup
# ---------------------------------------------------------------------------


def test_stdio_startup() -> None:
    """Send an initialize message over stdio and verify we get a response."""
    log.info(f"\n{BOLD}1. Stdio startup{RESET}")
    init_msg = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "smoke-test", "version": "0.1.0"},
            },
        }
    )
    try:
        result = subprocess.run(
            _server_cmd(),
            input=init_msg + "\n",
            capture_output=True,
            text=True,
            timeout=15,
        )
        stdout = result.stdout.strip()
        has_jsonrpc = '"jsonrpc"' in stdout
        record(
            "stdio startup — server responds to initialize",
            has_jsonrpc,
            f"stdout length={len(stdout)}" if has_jsonrpc else f"stdout: {stdout[:200]}",
        )
    except subprocess.TimeoutExpired:
        record("stdio startup — server responds to initialize", False, "timed out after 15s")
    except Exception as exc:
        record("stdio startup — server responds to initialize", False, str(exc))


# ---------------------------------------------------------------------------
# 2–6, 8–55: HTTP transport tests (run inside an async context)
# ---------------------------------------------------------------------------


async def run_http_tests() -> None:
    server_proc = None
    try:
        log.info(f"\n{BOLD}Starting HTTP server on port {SERVER_PORT}…{RESET}")
        server_proc = start_server()
        log.info("  Server started.\n")

        # -- 2. HTTP transport -------------------------------------------------
        log.info(f"{BOLD}2. HTTP transport{RESET}")
        try:
            async with mcp_session() as session:
                tools_result = await session.list_tools()
                tool_names = [t.name for t in tools_result.tools]
                has_tools = len(tool_names) > 0
                record(
                    "HTTP transport — list tools",
                    has_tools,
                    f"{len(tool_names)} tools found",
                )
        except Exception as exc:
            record("HTTP transport — list tools", False, str(exc))

        # -- 3. Correlation IDs ------------------------------------------------
        log.info(f"\n{BOLD}3. Correlation IDs{RESET}")
        try:
            async with mcp_session() as session:
                resp = await call_tool(session, "list_devices", {"limit": 1})
                cid = resp.get("metadata", {}).get("correlation_id")
                # Check it looks like a UUID
                valid_uuid = False
                if cid:
                    try:
                        uuid.UUID(cid)
                        valid_uuid = True
                    except ValueError:
                        # Malformed correlation id — leave valid_uuid False.
                        pass
                record(
                    "correlation_id present and valid UUID",
                    valid_uuid,
                    f"correlation_id={cid}" if cid else "missing",
                )
        except Exception as exc:
            record("correlation_id present and valid UUID", False, str(exc))

        # -- 4. Idempotency ----------------------------------------------------
        log.info(f"\n{BOLD}4. Idempotency{RESET}")
        try:
            async with mcp_session() as session:
                # First, grab a device_id for the command
                devices = await call_tool(session, "list_devices", {"limit": 1})
                device_list = _extract_list(devices.get("data"))
                if not device_list:
                    record("idempotency — cached response", False, "no devices in org")
                else:
                    device_id = _extract_id(device_list[0], "device_id", "id")
                    req_id = f"smoke-{uuid.uuid4()}"

                    resp1 = await _safe_call(
                        session,
                        "execute_device_command",
                        {
                            "device_id": device_id,
                            "command_type": "scan",
                            "request_id": req_id,
                        },
                    )
                    resp2 = await _safe_call(
                        session,
                        "execute_device_command",
                        {
                            "device_id": device_id,
                            "command_type": "scan",
                            "request_id": req_id,
                        },
                    )
                    if resp1 is None:
                        record(
                            "idempotency — cached response",
                            False,
                            "execute_device_command failed (API error?)",
                        )
                    else:
                        # The cached response should have the same correlation_id
                        cid1 = resp1.get("metadata", {}).get("correlation_id")
                        cid2 = (resp2 or {}).get("metadata", {}).get("correlation_id")
                        same = cid1 == cid2 and cid1 is not None
                        record(
                            "idempotency — cached response",
                            same,
                            f"cid1={cid1}, cid2={cid2}",
                        )
        except Exception as exc:
            record("idempotency — cached response", False, str(exc))

        # -- 5. Markdown output ------------------------------------------------
        # #177 contract: markdown mode returns a FastMCP ToolResult — the rendered
        # table is the TEXT content (for human-facing hosts) and the full structured
        # {data, metadata} object is preserved as structuredContent (for schema-aware
        # hosts). Assert BOTH channels directly off the CallToolResult; do NOT parse
        # content as JSON (it is now a markdown table, not JSON — the old contract
        # put the table string under data, which this asserted before #177).
        log.info(f"\n{BOLD}5. Markdown output{RESET}")
        try:
            async with mcp_session() as session:
                result = await session.call_tool(
                    "list_devices", {"limit": 3, "output_format": "markdown"}
                )
                table_text = next(
                    (b.text for b in result.content if isinstance(b, types.TextContent)), ""
                )
                has_table = "|" in table_text and "---" in table_text
                sc = result.structuredContent or {}
                has_structured = isinstance(sc.get("data"), (dict, list))
                record(
                    "markdown output — table in content + structured object preserved",
                    not result.isError and has_table and has_structured,
                    f"has_table={has_table}, structured_data={has_structured}",
                )
        except Exception as exc:
            record(
                "markdown output — table in content + structured object preserved", False, str(exc)
            )

        # -- 6. discover_capabilities ------------------------------------------
        log.info(f"\n{BOLD}6. discover_capabilities{RESET}")
        try:
            async with mcp_session() as session:
                # With domain
                resp_dev = await call_tool(session, "discover_capabilities", {"domain": "devices"})
                domain_ok = resp_dev.get("data", {}).get("domain") == "devices"
                tool_count = resp_dev.get("data", {}).get("tool_count", 0)
                has_tools_list = isinstance(resp_dev.get("data", {}).get("tools"), list)
                record(
                    "discover_capabilities — domain=devices",
                    domain_ok and tool_count > 0 and has_tools_list,
                    f"domain={resp_dev.get('data', {}).get('domain')}, tool_count={tool_count}",
                )

                # Without domain
                resp_all = await call_tool(session, "discover_capabilities", {})
                domains = resp_all.get("data", {}).get("available_domains", [])
                has_expected = "devices" in domains and "policies" in domains
                record(
                    "discover_capabilities — all domains",
                    has_expected and len(domains) >= 5,
                    f"domains={domains}",
                )
        except Exception as exc:
            record("discover_capabilities", False, str(exc))

        # -- 8–49: Read-only tool coverage ------------------------------------
        log.info(f"\n{BOLD}Read-only tool coverage{RESET}")
        await run_readonly_tools()

    finally:
        if server_proc:
            stop_server(server_proc)
            log.info("  HTTP server stopped.\n")


# ---------------------------------------------------------------------------
# 7. Non-loopback warning (separate server instance)
# ---------------------------------------------------------------------------


def test_non_loopback_warning() -> None:
    log.info(f"\n{BOLD}7. Non-loopback warning{RESET}")
    warn_port = SERVER_PORT + 1
    proc = None
    try:
        proc = start_server(
            "--host",
            "0.0.0.0",
            "--allow-remote-bind",
            port=warn_port,
            capture_stderr=True,
        )
        stderr = stop_server(proc)
        proc = None  # already stopped
        has_warning = "non-loopback" in stderr.lower()
        record(
            "non-loopback warning on --host 0.0.0.0",
            has_warning,
            f"stderr contains 'non-loopback': {has_warning}",
        )
    except Exception as exc:
        record("non-loopback warning on --host 0.0.0.0", False, str(exc))
    finally:
        if proc:
            stop_server(proc)


# ---------------------------------------------------------------------------
# Read-only tool battery (tests 8–55)
# ---------------------------------------------------------------------------


async def run_readonly_tools() -> None:
    """Exercise every read-only tool against the production org."""

    # We'll reuse one session and capture IDs along the way
    async with mcp_session() as session:
        device_id: int | None = None
        policy_id: int | None = None
        policy_uuid: str | None = None
        group_id: int | None = None

        # ---- Devices ----
        # 8. list_devices
        resp = await _safe_call(session, "list_devices", {"limit": 2})
        device_list = _extract_list(resp.get("data")) if resp else []
        record(
            "list_devices", resp is not None and len(device_list) > 0, f"count={len(device_list)}"
        )
        if device_list:
            device_id = _extract_id(device_list[0], "device_id", "id")

        # 9. device_detail
        if device_id:
            resp = await _safe_call(session, "device_detail", {"device_id": device_id})
            ok = resp is not None and resp.get("data") is not None
            note = f"id={device_id}"
            if ok and resp is not None:
                # Correctness, not just 200: per-policy statuses must be the
                # translated vocabulary (raw "0"/"1"/"2" means the integer
                # enum mapping regressed), and the compliance rollup must
                # account for every policy_status entry.
                core = resp["data"].get("core") or {}
                statuses = {e.get("status") for e in core.get("policy_status") or []}
                raw_codes = statuses & {"0", "1", "2"}
                if raw_codes:
                    ok = False
                    note = f"raw status codes leaked: {sorted(raw_codes)}"
                compliance = resp["data"].get("compliance") or {}
                counts = compliance.get("policy_status_counts")
                total = (resp.get("metadata") or {}).get("policy_status_total")
                if ok and counts is not None and sum(counts.values()) != total:
                    ok = False
                    note = f"compliance counts {sum(counts.values())} != total {total}"
                if ok and "uptime" in core:
                    ok = False
                    note = "unit-less `uptime` key present (expected uptime_minutes)"
            record("device_detail", ok, note)
        else:
            record("device_detail", False, "skipped — no device_id")

        # 10. search_devices
        resp = await _safe_call(session, "search_devices", {"hostname_contains": "a", "limit": 2})
        record("search_devices", resp is not None, _count_or_err(resp))

        # 11. devices_needing_attention
        resp = await _safe_call(session, "devices_needing_attention", {"limit": 2})
        record("devices_needing_attention", resp is not None, _count_or_err(resp))

        # 12. device_health_metrics
        resp = await _safe_call(session, "device_health_metrics", {})
        record(
            "device_health_metrics", resp is not None and "data" in (resp or {}), _data_keys(resp)
        )

        # ---- Policies ----
        # 13. policy_catalog
        resp = await _safe_call(session, "policy_catalog", {"limit": 20})
        policy_list = _extract_list(resp.get("data")) if resp else []
        record(
            "policy_catalog", resp is not None and len(policy_list) > 0, f"count={len(policy_list)}"
        )
        if policy_list:
            policy_id = _extract_id(policy_list[0], "policy_id", "id")
            policy_uuid = policy_list[0].get("policy_uuid")

        # 14. policy_detail
        if policy_id:
            resp = await _safe_call(session, "policy_detail", {"policy_id": policy_id})
            # Also try to extract policy_uuid from detail if not yet found
            if not policy_uuid and resp and resp.get("data"):
                detail_data = resp["data"]
                policy_uuid = (
                    detail_data.get("policy_uuid")
                    or detail_data.get("guid")
                    or detail_data.get("uuid")
                )
            record(
                "policy_detail",
                resp is not None and resp.get("data") is not None,
                f"id={policy_id}, uuid={policy_uuid}",
            )
        else:
            record("policy_detail", False, "skipped — no policy_id")

        # 15. policy_health_overview
        resp = await _safe_call(session, "policy_health_overview", {})
        record(
            "policy_health_overview", resp is not None and "data" in (resp or {}), _data_keys(resp)
        )

        # 16. policy_compliance_stats (takes no parameters)
        resp = await _safe_call(session, "policy_compliance_stats", {})
        record("policy_compliance_stats", resp is not None, _data_keys(resp))

        # 17. policy_execution_timeline (needs policy_uuid)
        # Try each policy until we find one with execution history
        exec_token: str | None = None
        timeline_tested = False
        candidates = [policy_uuid] if policy_uuid else []
        candidates += [p.get("policy_uuid") for p in policy_list[1:5] if p.get("policy_uuid")]
        for candidate_uuid in candidates:
            if not candidate_uuid:
                continue
            resp = await _safe_call(
                session, "policy_execution_timeline", {"policy_uuid": candidate_uuid, "limit": 2}
            )
            if not timeline_tested:
                record("policy_execution_timeline", resp is not None, _count_or_err(resp))
                timeline_tested = True
            if resp and resp.get("data"):
                tl_data = resp["data"]
                runs = (
                    tl_data.get("recent_executions", [])
                    if isinstance(tl_data, dict)
                    else _extract_list(tl_data)
                )
                if runs:
                    exec_token = runs[0].get("exec_token") or runs[0].get("execution_token")
                    policy_uuid = candidate_uuid  # use this policy for run_results
                    break
        if not timeline_tested:
            record("policy_execution_timeline", False, "skipped — no policy_uuid")

        # ---- Server Groups ----
        # 18. list_server_groups
        resp = await _safe_call(session, "list_server_groups", {})
        group_list = _extract_list(resp.get("data")) if resp else []
        record(
            "list_server_groups",
            resp is not None and len(group_list) > 0,
            f"count={len(group_list)}",
        )
        if group_list:
            group_id = _extract_id(group_list[0], "id", "server_group_id")

        # 19. get_server_group
        if group_id:
            resp = await _safe_call(session, "get_server_group", {"group_id": group_id})
            record(
                "get_server_group",
                resp is not None and resp.get("data") is not None,
                f"id={group_id}",
            )
        else:
            record("get_server_group", False, "skipped — no group_id")

        # ---- Events ----
        # 20. list_events
        resp = await _safe_call(session, "list_events", {"limit": 2})
        record("list_events", resp is not None, _count_or_err(resp))

        # ---- Packages ----
        # 21. list_device_packages — assert COMPLETENESS, not just "got a response".
        # The endpoint returns a bare list with no total and pages 0-indexed by
        # `limit`; a single page silently truncates (the #132 bug). Calling with
        # no `limit` auto-paginates the full set and sets metadata.complete — so
        # we assert that flag rather than accepting any non-empty page.
        if device_id:
            resp = await _safe_call(session, "list_device_packages", {"device_id": device_id})
            complete = (resp or {}).get("metadata", {}).get("complete")
            total = (resp or {}).get("data", {}).get("total_packages")
            pkgs = (resp or {}).get("data", {}).get("packages", []) or []
            # Phantom regression detector: `patch_status` is not a live field
            # and must never reappear in any entry. The severity legend is
            # attached unconditionally.
            no_phantom = all("patch_status" not in p for p in pkgs)
            has_legend = "severity" in (resp or {}).get("metadata", {}).get("field_notes", {})
            record(
                "list_device_packages",
                resp is not None and complete is True and no_phantom and has_legend,
                f"total={total} complete={complete} "
                f"no_patch_status={no_phantom} legend={has_legend}",
            )
        else:
            record("list_device_packages", False, "skipped — no device_id")

        # 22. search_org_packages — assert phantom `awaiting` output key never
        # reappears, the severity legend is present (unconditional), and the
        # count is page-scoped with a truncation signal (the endpoint is a bare
        # list with no total). A full page (count == limit) must flag has_more
        # and report `returned_package_count` (not a fleet-wide `total_packages`).
        resp = await _safe_call(session, "search_org_packages", {"limit": 2})
        org_data = (resp or {}).get("data", {})
        org_pkgs = org_data.get("packages", []) or []
        no_awaiting = all("awaiting" not in p for p in org_pkgs)
        org_legend = "severity" in (resp or {}).get("metadata", {}).get("field_notes", {})
        org_pagination = (resp or {}).get("metadata", {}).get("pagination", {})
        returned = org_data.get("returned_package_count")
        # Page-scoped count, no fleet-wide total leaked, full page → has_more.
        page_scoped = "total_packages" not in org_data and returned == len(org_pkgs)
        truncation_ok = (returned or 0) < 2 or org_pagination.get("has_more") is True
        record(
            "search_org_packages",
            resp is not None and no_awaiting and org_legend and page_scoped and truncation_ok,
            f"returned={returned} no_awaiting={no_awaiting} legend={org_legend} "
            f"page_scoped={page_scoped} has_more={org_pagination.get('has_more')}",
        )

        # ---- Reports ----
        # 23. noncompliant_report
        resp = await _safe_call(session, "noncompliant_report", {})
        nc_ok = resp is not None and "data" in (resp or {})
        nc_detail = _data_keys(resp)
        if nc_ok:
            # Correctness: when a device with failing_policies is present, at least
            # one policy should carry a non-empty reason_for_fail (finding 33;
            # live-verified populated 2026-06-05). Tenant state drifts and smoke
            # is manual/not-in-CI, so guard on presence rather than failing on a
            # healthy/empty tenant.
            ncdevs = (resp or {}).get("data", {}).get("devices", [])
            pols = [
                p for d in ncdevs if isinstance(d, dict) for p in (d.get("failing_policies") or [])
            ]
            if pols:
                has_reason = any(
                    isinstance(p.get("reason_for_fail"), str) and p["reason_for_fail"].strip()
                    for p in pols
                )
                has_fields = all(("type" in p and "severity" in p) for p in pols)
                nc_ok = has_reason and has_fields
                nc_detail = f"{len(pols)} policies; reason_for_fail+fields={nc_ok}"
        record("noncompliant_report", nc_ok, nc_detail)

        # 24. get_compliance_snapshot
        resp = await _safe_call(session, "get_compliance_snapshot", {})
        record(
            "get_compliance_snapshot", resp is not None and "data" in (resp or {}), _data_keys(resp)
        )

        # 25. audit_trail_user_activity (date is required)
        from datetime import date as date_cls

        today = date_cls.today().isoformat()
        resp = await _safe_call(session, "audit_trail_user_activity", {"date": today, "limit": 2})
        record("audit_trail_user_activity", resp is not None, _count_or_err(resp))

        # ---- Webhooks ----
        # 26. list_webhooks
        resp = await _safe_call(session, "list_webhooks", {})
        record("list_webhooks", resp is not None, _count_or_err(resp))

        # 27. list_webhook_event_types
        resp = await _safe_call(session, "list_webhook_event_types", {})
        record("list_webhook_event_types", resp is not None, _count_or_err(resp))

        # ---- More reports ----
        # 28. prepatch_report
        resp = await _safe_call(session, "prepatch_report", {})
        pp_ok = resp is not None and "data" in (resp or {})
        pp_detail = _data_keys(resp)
        if pp_ok:
            data = (resp or {}).get("data", {})
            meta = (resp or {}).get("metadata", {})
            # Correctness: the field_notes legend must be present, and any device
            # whose patches are all no_known_cves must project highest_severity ==
            # 'no_known_cves' (finding 31; not 'unknown'). The all-no_known_cves
            # device is tenant-state dependent — guard on finding one rather than
            # requiring it unconditionally.
            has_notes = bool(meta.get("field_notes"))
            has_nkc_bucket = "no_known_cves" in data.get("summary", {})
            # If the recomputed summary counted any no_known_cves device, at least
            # one device must carry highest_severity == 'no_known_cves'.
            nkc_count = data.get("summary", {}).get("no_known_cves", 0)
            devs = data.get("devices", [])
            nkc_devices = [
                d
                for d in devs
                if isinstance(d, dict) and d.get("highest_severity") == "no_known_cves"
            ]
            collapse_ok = (nkc_count == 0) or (len(nkc_devices) >= 1)
            pp_ok = has_notes and has_nkc_bucket and collapse_ok
            pp_detail = (
                f"notes={has_notes} nkc_bucket={has_nkc_bucket} nkc_devices={len(nkc_devices)}"
            )
        record("prepatch_report", pp_ok, pp_detail)

        # 29. patch_approvals_summary
        resp = await _safe_call(session, "patch_approvals_summary", {})
        record("patch_approvals_summary", resp is not None, _data_keys(resp))

        # 30. get_patch_tuesday_readiness
        resp = await _safe_call(session, "get_patch_tuesday_readiness", {})
        record(
            "get_patch_tuesday_readiness",
            resp is not None and "data" in (resp or {}),
            _data_keys(resp),
        )

        # ---- Compound / inventory ----
        # 31. get_device_full_profile
        if device_id:
            resp = await _safe_call(session, "get_device_full_profile", {"device_id": device_id})
            record(
                "get_device_full_profile",
                resp is not None and "data" in (resp or {}),
                _data_keys(resp),
            )
        else:
            record("get_device_full_profile", False, "skipped — no device_id")

        # 32. get_device_inventory
        if device_id:
            resp = await _safe_call(session, "get_device_inventory", {"device_id": device_id})
            record("get_device_inventory", resp is not None, _data_keys(resp))
        else:
            record("get_device_inventory", False, "skipped — no device_id")

        # 33. get_device_inventory_categories
        if device_id:
            resp = await _safe_call(
                session, "get_device_inventory_categories", {"device_id": device_id}
            )
            record("get_device_inventory_categories", resp is not None, _data_keys(resp))
        else:
            record("get_device_inventory_categories", False, "skipped — no device_id")

        # 34. policy_run_results (needs policy_uuid + exec_token)
        if policy_uuid and exec_token:
            resp = await _safe_call(
                session,
                "policy_run_results",
                {"policy_uuid": policy_uuid, "exec_token": exec_token, "limit": 2},
            )
            record("policy_run_results", resp is not None, _count_or_err(resp))
        else:
            record(
                "policy_run_results",
                False,
                f"skipped — policy_uuid={policy_uuid}, exec_token={exec_token}",
            )

        # ================================================================
        # Phase 3 tools (tests 35–49)
        # ================================================================

        log.info(f"\n{BOLD}Phase 3: Worklets{RESET}")

        # 35. search_worklet_catalog
        resp = await _safe_call(session, "search_worklet_catalog", {})
        record("search_worklet_catalog", resp is not None, _count_or_err(resp))

        # 36. get_worklet_detail (needs a worklet ID from catalog)
        worklet_list = _extract_list(resp.get("data")) if resp else []
        worklet_id = None
        for wl in worklet_list:
            wl_id = wl.get("id") or wl.get("wis_id") or wl.get("uuid")
            if wl_id:
                worklet_id = wl_id
                break
        if worklet_id:
            resp = await _safe_call(session, "get_worklet_detail", {"item_id": str(worklet_id)})
            record("get_worklet_detail", resp is not None, _data_keys(resp))
        else:
            record("get_worklet_detail", False, "skipped — no worklet_id from catalog")

        log.info(f"\n{BOLD}Phase 3: Data Extracts{RESET}")

        # 37. list_data_extracts — assert ENVELOPE-UNWRAP CORRECTNESS, not just
        # "got a response". The live endpoint returns a {results, size} envelope
        # (the #163 fix unwraps it). A regressed unwrap that left the whole
        # envelope dict as a single row would still pass resp-is-not-None: it
        # would surface extracts=[{results:[...], size:N}] (one row, no `id`)
        # while reporting total_extracts=1. So reconcile the envelope: every
        # row must be an extract dict carrying an `id` (never a nested
        # `results` key), and total_extracts (the envelope `size`) must be an
        # int >= the page row count (size is the grand total across pages; the
        # rows are a single page, so rows can be < size but never > size).
        resp = await _safe_call(session, "list_data_extracts", {})
        data = (resp or {}).get("data", {})
        total = data.get("total_extracts")
        rows = data.get("extracts", []) or []
        unwrap_ok = (
            resp is not None
            and isinstance(total, int)
            and isinstance(rows, list)
            and total >= len(rows)
            and all(isinstance(r, dict) and "results" not in r for r in rows)
            # non-empty page rows must each carry the unwrapped `id` key
            and all("id" in r for r in rows)
        )
        record("list_data_extracts", unwrap_ok, f"size={total} rows={len(rows)}")

        log.info(f"\n{BOLD}Phase 3: Org API Keys{RESET}")

        # 38. list_org_api_keys — correctness, not just 200. GET
        # /orgs/{id}/api_keys returns a {"results", "size"} envelope; a regressed
        # unwrap (the N1 bug) returned zero keys while size was 21. Assert the
        # projected key count reconciles to the envelope size (count == size),
        # per the CLAUDE.md wrong-but-200 smoke convention.
        resp = await _safe_call(session, "list_org_api_keys", {})
        if resp is None:
            record("list_org_api_keys", False, _count_or_err(resp))
        else:
            data = resp.get("data") or {}
            meta = resp.get("metadata") or {}
            total_keys = data.get("total_keys")
            total_size = meta.get("total_size")
            # Default page returns the full set on this tenant, so count==size.
            reconciles = (
                isinstance(total_size, int)
                and isinstance(total_keys, int)
                and total_keys == total_size
            )
            record(
                "list_org_api_keys",
                reconciles,
                f"total_keys={total_keys} reconciles to size={total_size}",
            )

        log.info(f"\n{BOLD}Phase 3: Policy History v2{RESET}")

        # 39. policy_runs_v2
        resp = await _safe_call(session, "policy_runs_v2", {"limit": 5})
        record("policy_runs_v2", resp is not None, _count_or_err(resp))

        # 40. policy_run_count
        resp = await _safe_call(session, "policy_run_count", {"days": 30})
        record("policy_run_count", resp is not None, _data_keys(resp))

        # 41. policy_runs_by_policy
        resp = await _safe_call(session, "policy_runs_by_policy", {})
        record("policy_runs_by_policy", resp is not None, _count_or_err(resp))

        # 42. policy_history_detail (needs policy_uuid)
        if policy_uuid:
            resp = await _safe_call(session, "policy_history_detail", {"policy_uuid": policy_uuid})
            record("policy_history_detail", resp is not None, _data_keys(resp))
        else:
            record("policy_history_detail", False, "skipped — no policy_uuid")

        # 43. policy_runs_for_policy (needs policy_uuid)
        if policy_uuid:
            resp = await _safe_call(
                session,
                "policy_runs_for_policy",
                {"policy_uuid": policy_uuid, "report_days": 7},
            )
            record("policy_runs_for_policy", resp is not None, _count_or_err(resp))
        else:
            record("policy_runs_for_policy", False, "skipped — no policy_uuid")

        log.info(f"\n{BOLD}Phase 3: Audit v2 (OCSF){RESET}")

        # 44. audit_events_ocsf — correctness, not just 200. The upstream has no
        # category_name field, so the category filter narrows on the type_name
        # prefix. Assert: (a) a known category token sets matched=true and never
        # widens the result, and (b) an unmappable token does NOT zero the result
        # (it leaves it unfiltered, matched=false) — that was the silent-zero bug.
        resp_all = await _safe_call(session, "audit_events_ocsf", {"date": today, "limit": 50})
        total_all = (resp_all or {}).get("data", {}).get("total_events")
        resp_cat = await _safe_call(
            session,
            "audit_events_ocsf",
            {"date": today, "limit": 50, "category_name": "web_resource_activity"},
        )
        resp_bogus = await _safe_call(
            session,
            "audit_events_ocsf",
            {"date": today, "limit": 50, "category_name": "__no_such_category__"},
        )
        cat_md = (resp_cat or {}).get("metadata", {}).get("applied_filters", {})
        bogus_data = (resp_bogus or {}).get("data", {})
        bogus_md = (resp_bogus or {}).get("metadata", {}).get("applied_filters", {})
        ocsf_ok = (
            resp_all is not None
            and resp_cat is not None
            and resp_bogus is not None
            and isinstance(total_all, int)
            and cat_md.get("category_name_matched") is True
            and (resp_cat or {}).get("data", {}).get("total_events", 0) <= total_all
            # unknown token must not be mistaken for "no activity"
            and bogus_md.get("category_name_matched") is False
            and bogus_data.get("total_events") == total_all
        )
        record(
            "audit_events_ocsf",
            ocsf_ok,
            f"unfiltered={total_all} cat_matched={cat_md.get('category_name_matched')} "
            f"bogus_matched={bogus_md.get('category_name_matched')}",
        )

        log.info(f"\n{BOLD}Phase 3: Advanced Device Search{RESET}")

        # 45. list_saved_searches
        resp = await _safe_call(session, "list_saved_searches", {})
        record("list_saved_searches", resp is not None, _count_or_err(resp))

        # 46. get_device_metadata_fields
        resp = await _safe_call(session, "get_device_metadata_fields", {})
        record("get_device_metadata_fields", resp is not None, _count_or_err(resp))

        # 47. get_device_assignments
        resp = await _safe_call(session, "get_device_assignments", {})
        record("get_device_assignments", resp is not None, _count_or_err(resp))

        log.info(f"\n{BOLD}Phase 3: Vulnerability Sync{RESET}")

        # 48. list_remediation_action_sets
        resp = await _safe_call(session, "list_remediation_action_sets", {})
        record("list_remediation_action_sets", resp is not None, _count_or_err(resp))

        # 49. get_upload_formats
        resp = await _safe_call(session, "get_upload_formats", {})
        record("get_upload_formats", resp is not None, _count_or_err(resp))

        # ================================================================
        # Policy Windows (tests 50–55)
        # ================================================================

        log.info(f"\n{BOLD}Policy Windows{RESET}")

        # 50. search_policy_windows
        resp = await _safe_call(session, "search_policy_windows", {})
        record("search_policy_windows", resp is not None, _count_or_err(resp))
        window_list = _extract_list(resp.get("data")) if resp else []
        window_uuid: str | None = None
        for w in window_list:
            w_uuid = w.get("window_uuid")
            if w_uuid:
                window_uuid = w_uuid
                break

        # 51. get_policy_window (needs a window_uuid from search)
        if window_uuid:
            resp = await _safe_call(session, "get_policy_window", {"window_uuid": window_uuid})
            record("get_policy_window", resp is not None, _data_keys(resp))
        else:
            record("get_policy_window", True, "skipped — no windows in org (OK)")

        # 52. check_window_active (needs a window_uuid)
        if window_uuid:
            resp = await _safe_call(session, "check_window_active", {"window_uuid": window_uuid})
            record("check_window_active", resp is not None, _data_keys(resp))
        else:
            record("check_window_active", True, "skipped — no windows in org (OK)")

        # 53. check_group_exclusion_status (needs group UUIDs)
        # Use the first group's UUID if available from earlier tests
        if group_list:
            g_uuid = group_list[0].get("uuid") or group_list[0].get("group_uuid")
            if g_uuid:
                resp = await _safe_call(
                    session,
                    "check_group_exclusion_status",
                    {"group_uuids": [g_uuid]},
                )
                record("check_group_exclusion_status", resp is not None, _data_keys(resp))
            else:
                record(
                    "check_group_exclusion_status",
                    True,
                    "skipped — no group UUID available (OK)",
                )
        else:
            record(
                "check_group_exclusion_status",
                True,
                "skipped — no groups in org (OK)",
            )

        # 54. get_group_scheduled_windows (needs a group UUID)
        if group_list:
            g_uuid = group_list[0].get("uuid") or group_list[0].get("group_uuid")
            if g_uuid:
                resp = await _safe_call(
                    session,
                    "get_group_scheduled_windows",
                    {"group_uuid": g_uuid, "date": "2026-12-31T00:00:00"},
                )
                record("get_group_scheduled_windows", resp is not None, _data_keys(resp))
            else:
                record(
                    "get_group_scheduled_windows",
                    True,
                    "skipped — no group UUID available (OK)",
                )
        else:
            record(
                "get_group_scheduled_windows",
                True,
                "skipped — no groups in org (OK)",
            )

        # 55. get_device_scheduled_windows (needs a device UUID)
        if device_list:
            d_uuid = device_list[0].get("uuid") or device_list[0].get("device_uuid")
            if d_uuid:
                resp = await _safe_call(
                    session,
                    "get_device_scheduled_windows",
                    {"device_uuid": d_uuid, "date": "2026-12-31T00:00:00"},
                )
                record("get_device_scheduled_windows", resp is not None, _data_keys(resp))
            else:
                record(
                    "get_device_scheduled_windows",
                    True,
                    "skipped — no device UUID available (OK)",
                )
        else:
            record(
                "get_device_scheduled_windows",
                True,
                "skipped — no devices in org (OK)",
            )

        # ================================================================
        # Phase 4: #91 identity / API-key-metadata / device-search-
        # enrichment / policy-device-targeting read tools (tests 56+).
        #
        # These are the 1.2.0 #91 wave the smoke script had not kept pace
        # with. Read-only; dependent calls chain IDs from their list call
        # and skip-OK when the org has no such records.
        # ================================================================

        device_uuid: str | None = None
        if device_list:
            device_uuid = device_list[0].get("uuid") or device_list[0].get("device_uuid")

        # ---- Identity / account ----
        log.info(f"\n{BOLD}Phase 4: Identity / Account{RESET}")

        # 56. list_users — account-admin scope; skip-OK if the key lacks it (403).
        resp = await _safe_call(session, "list_users", {"limit": 5}, tolerate=(403, 404))
        if resp is _TOLERATED:
            record("list_users", True, "skipped — key lacks user-admin scope (OK)")
            users = []
        else:
            users = _extract_list(resp.get("data")) if resp else []
            record("list_users", resp is not None, f"count={len(users)}")
        user_id = _extract_id(users[0], "id", "user_id") if users else None

        # 57. get_user
        if user_id:
            resp = await _safe_call(session, "get_user", {"user_id": user_id})
            record("get_user", resp is not None, f"id={user_id}")
        else:
            record("get_user", True, "skipped — no users in org (OK)")

        # 58. get_account_user
        if user_id:
            resp = await _safe_call(session, "get_account_user", {"user_id": user_id})
            record("get_account_user", resp is not None, f"id={user_id}")
        else:
            record("get_account_user", True, "skipped — no user_id (OK)")

        # 59. list_zones_for_user
        if user_id:
            resp = await _safe_call(session, "list_zones_for_user", {"user_id": user_id})
            record("list_zones_for_user", resp is not None, _count_or_err(resp))
        else:
            record("list_zones_for_user", True, "skipped — no user_id (OK)")

        # 60. list_user_api_keys
        key_id = None
        if user_id:
            resp = await _safe_call(session, "list_user_api_keys", {"user_id": user_id})
            record("list_user_api_keys", resp is not None, _count_or_err(resp))
            keys = _extract_list(resp.get("data")) if resp else []
            if keys:
                key_id = _extract_id(keys[0], "id", "key_id")
        else:
            record("list_user_api_keys", True, "skipped — no user_id (OK)")

        # 61. get_user_api_key
        if user_id and key_id:
            resp = await _safe_call(
                session, "get_user_api_key", {"user_id": user_id, "key_id": key_id}
            )
            record("get_user_api_key", resp is not None, f"key_id={key_id}")
        else:
            record("get_user_api_key", True, "skipped — no user API keys (OK)")

        # 62. get_account — needs the account UUID + account scope; skip-OK on
        # 403/404 (a limited or org-scoped key can't read account detail).
        resp = await _safe_call(session, "get_account", {}, tolerate=(403, 404))
        if resp is _TOLERATED:
            record("get_account", True, "skipped — key lacks account scope (OK)")
        else:
            record("get_account", resp is not None and "data" in (resp or {}), _data_keys(resp))

        # 63. list_account_rbac_roles
        resp = await _safe_call(session, "list_account_rbac_roles", {}, tolerate=(403, 404))
        if resp is _TOLERATED:
            record("list_account_rbac_roles", True, "skipped — key lacks account scope (OK)")
        else:
            record("list_account_rbac_roles", resp is not None, _count_or_err(resp))

        # 64. list_organizations
        resp = await _safe_call(session, "list_organizations", {"limit": 5})
        record("list_organizations", resp is not None, _count_or_err(resp))

        # 65. list_global_api_keys — requires a global-scope key; skip-OK on 403.
        resp = await _safe_call(session, "list_global_api_keys", {}, tolerate=(403, 404))
        if resp is _TOLERATED:
            record("list_global_api_keys", True, "skipped — key lacks global scope (OK)")
        else:
            record("list_global_api_keys", resp is not None, _count_or_err(resp))

        # ---- Zones ----
        # 66. list_zones
        resp = await _safe_call(session, "list_zones", {"limit": 5}, tolerate=(403, 404))
        if resp is _TOLERATED:
            record("list_zones", True, "skipped — key lacks account scope (OK)")
            zones = []
        else:
            zones = _extract_list(resp.get("data")) if resp else []
            record("list_zones", resp is not None, f"count={len(zones)}")
        zone_id = None
        if zones:
            zone_id = zones[0].get("id") or zones[0].get("uuid") or zones[0].get("zone_id")

        # 67. get_zone
        if zone_id:
            resp = await _safe_call(session, "get_zone", {"zone_id": zone_id})
            record("get_zone", resp is not None, f"zone_id={zone_id}")
        else:
            record("get_zone", True, "skipped — no zones in org (OK)")

        # 68. list_zone_users — assert the secret-stripping projection holds LIVE.
        # The zone-member User DTO carries `intercom_hmac` (a chat-auth secret) and
        # the zone DTO carries `access_key`; the wrapper must project both out (#194).
        # A raw forward would return 200 with the secret present, so "got a response"
        # is insufficient — assert the secret is absent from the serialized payload.
        if zone_id:
            resp = await _safe_call(session, "list_zone_users", {"zone_id": zone_id})
            if resp is None:
                record("list_zone_users", False, "call failed")
            else:
                blob = json.dumps(resp)
                leaked = "intercom_hmac" in blob or "access_key" in blob
                record(
                    "list_zone_users",
                    not leaked,
                    "SECRET LEAKED in payload!" if leaked else f"{_count_or_err(resp)}, no secret",
                )
        else:
            record("list_zone_users", True, "skipped — no zone_id (OK)")

        # ---- Device-search enrichment ----
        log.info(f"\n{BOLD}Phase 4: Device-search enrichment{RESET}")

        # 69. advanced_device_search — assert the filter NARROWS the result.
        # The #132 bug returned 200 with the *whole fleet* because the filter was
        # placed under the wrong body key and silently ignored; a "got a response"
        # check sails right past that. We compare an unfiltered count against a
        # filter that matches nothing when honored (a bogus OS value): if the
        # filter is honored the count drops to ~0; if ignored it equals the fleet.
        resp_all = await _safe_call(session, "advanced_device_search", {"query": {}, "limit": 1})
        total_all = (resp_all or {}).get("data", {}).get("total_devices")
        no_match_query = {
            "filters": [
                {
                    "AND": [
                        {
                            "scope": "DEVICE",
                            "field": "osFamilyName",
                            "operator": "EQ",
                            "values": ["__no_such_os__smoke_probe__"],
                        }
                    ]
                }
            ]
        }
        resp_filtered = await _safe_call(
            session, "advanced_device_search", {"query": no_match_query, "limit": 1}
        )
        total_filtered = (resp_filtered or {}).get("data", {}).get("total_devices")
        narrows = (
            resp_all is not None
            and resp_filtered is not None
            and isinstance(total_all, int)
            and isinstance(total_filtered, int)
            and total_all > 0
            and total_filtered < total_all
        )
        record(
            "advanced_device_search",
            narrows,
            f"unfiltered={total_all} filtered={total_filtered}",
        )

        # 70. device_search_typeahead — `name` is a valid typeahead field;
        # `hostname` is not (the endpoint 400s on unknown fields).
        resp = await _safe_call(
            session, "device_search_typeahead", {"field": "name", "prefix": "a"}
        )
        record("device_search_typeahead", resp is not None, _count_or_err(resp))

        # 71. get_search_scopes
        resp = await _safe_call(session, "get_search_scopes", {})
        record("get_search_scopes", resp is not None, _count_or_err(resp))

        # 72. get_searchable_fields
        resp = await _safe_call(session, "get_searchable_fields", {})
        record("get_searchable_fields", resp is not None, _count_or_err(resp))

        # 73. get_device_by_uuid
        if device_uuid:
            resp = await _safe_call(session, "get_device_by_uuid", {"device_uuid": device_uuid})
            ok = resp is not None
            note = f"uuid={device_uuid}"
            if ok and resp is not None:
                # Correctness: the raw payload must carry the legend — every
                # integer policy code labeled, uptime_minutes instead of the
                # unit-less raw key (regression guard for the device_detail
                # twin fix).
                detail = resp.get("data") or {}
                unlabeled = [
                    p
                    for p in detail.get("policy_status") or []
                    if isinstance(p.get("status"), int) and "status_label" not in p
                ]
                if unlabeled:
                    ok = False
                    note = f"{len(unlabeled)} integer policy codes without status_label"
                elif "uptime" in detail:
                    ok = False
                    note = "unit-less `uptime` key present (expected uptime_minutes)"
            record("get_device_by_uuid", ok, note)
        else:
            record("get_device_by_uuid", True, "skipped — no device uuid (OK)")

        # 74. list_searches_for_device
        if device_uuid:
            resp = await _safe_call(
                session, "list_searches_for_device", {"device_uuid": device_uuid}
            )
            record("list_searches_for_device", resp is not None, _count_or_err(resp))
        else:
            record("list_searches_for_device", True, "skipped — no device uuid (OK)")

        # 75–78. Saved-search detail tools (need a saved search to exist)
        resp = await _safe_call(session, "list_saved_searches", {})
        saved = _extract_list(resp.get("data")) if resp else []
        saved_id = _extract_id(saved[0], "id", "saved_search_id") if saved else None
        saved_uuid = None
        if saved:
            saved_uuid = (
                saved[0].get("uuid")
                or saved[0].get("saved_search_uuid")
                or saved[0].get("search_uuid")
            )

        # 75. get_saved_search
        if saved_id:
            resp = await _safe_call(session, "get_saved_search", {"saved_search_id": saved_id})
            record("get_saved_search", resp is not None, f"id={saved_id}")
        else:
            record("get_saved_search", True, "skipped — no saved searches (OK)")

        # 76. get_saved_search_results
        if saved_id:
            resp = await _safe_call(
                session, "get_saved_search_results", {"saved_search_id": saved_id, "limit": 2}
            )
            record("get_saved_search_results", resp is not None, _count_or_err(resp))
        else:
            record("get_saved_search_results", True, "skipped — no saved searches (OK)")

        # 77. run_saved_search (by UUID)
        if saved_uuid:
            resp = await _safe_call(
                session, "run_saved_search", {"search_id": saved_uuid, "size": 2}
            )
            record("run_saved_search", resp is not None, _count_or_err(resp))
        else:
            record("run_saved_search", True, "skipped — no saved-search uuid (OK)")

        # 78. get_cached_search_results — keyed by a prior *search execution* id,
        # which this read-only smoke pass doesn't create, so there's no reliable
        # id to pass. Skip-OK rather than guess a wrong key.
        record(
            "get_cached_search_results",
            True,
            "skipped — needs a prior search-execution id (OK)",
        )

        # 78b. Saved-search WRITE round-trip (create → update → delete).
        # create_saved_search / update_saved_search returned HTTP 500 on every
        # structured query (#132) — invisible to the read-only path. This is a
        # self-cleaning write: a uniquely-named throwaway search is always
        # deleted (best-effort) even if an assertion fails, so it leaves no
        # residue in the tenant.
        ss_name = f"mcp-smoke-delete-me-{uuid.uuid4().hex[:8]}"
        ss_query = {
            "filters": [
                {
                    "AND": [
                        {
                            "scope": "SOFTWARE",
                            "field": "pkgDisplayName",
                            "operator": "IN",
                            "values": ["nginx"],
                        }
                    ]
                }
            ]
        }
        created = await _safe_call(
            session, "create_saved_search", {"name": ss_name, "query": ss_query}
        )
        # The saved-search id is a UUID *string*; read it directly (don't use
        # _extract_id, which coerces to int and would raise on a UUID).
        new_id = created.get("data", {}).get("id") if created else None
        record(
            "create_saved_search",
            bool(created and created.get("data", {}).get("created") and new_id),
            f"id={new_id}",
        )
        try:
            if new_id:
                # Name-only update exercises the read-modify-write path: the
                # upstream PUT is full-replace and 500s on a partial body.
                updated = await _safe_call(
                    session,
                    "update_saved_search",
                    {"saved_search_id": new_id, "name": f"{ss_name}-renamed"},
                )
                record(
                    "update_saved_search",
                    bool(updated and updated.get("data", {}).get("updated")),
                    f"id={new_id}",
                )
            else:
                record("update_saved_search", False, "skipped — create failed")
        finally:
            if new_id:
                deleted = await _safe_call(
                    session, "delete_saved_search", {"saved_search_id": new_id}
                )
                record(
                    "delete_saved_search",
                    bool(deleted and deleted.get("data", {}).get("deleted")),
                    f"id={new_id}",
                )
            else:
                record("delete_saved_search", False, "skipped — create failed")

        # ---- Policy device-targeting ----
        log.info(f"\n{BOLD}Phase 4: Policy device-targeting{RESET}")

        # 79. preview_policy_device_filters — assert CORRECTNESS, not just 200.
        # The {results, size} envelope was once mis-parsed as ONE device
        # (total_devices=1 for any result set), and a wrong-but-200 preview
        # defeats the tool's purpose as a blast-radius check. Two assertions:
        # the reported total matches the returned device list, and a filter for
        # a nonexistent tag narrows the group scope to exactly 0 devices.
        # (server_groups is required alongside device_filters — a filter-only
        # body 500s upstream and is now rejected client-side.)
        if group_id:
            base = await _safe_call(
                session,
                "preview_policy_device_filters",
                {"server_groups": [group_id]},
            )
            filt = await _safe_call(
                session,
                "preview_policy_device_filters",
                {
                    "server_groups": [group_id],
                    "device_filters": [
                        {"field": "tag", "op": "in", "value": ["smoke-no-such-tag-zzz"]}
                    ],
                },
            )
            base_data = (base or {}).get("data", {})
            filt_data = (filt or {}).get("data", {})
            base_total = base_data.get("total_devices")
            filt_total = filt_data.get("total_devices")
            ok = (
                isinstance(base_total, int)
                and base_total == len(base_data.get("devices") or [])
                and filt_total == 0
            )
            record(
                "preview_policy_device_filters",
                ok,
                f"group scope={base_total}, impossible-tag filter={filt_total} (expect 0)",
            )
        else:
            record("preview_policy_device_filters", True, "skipped — no server group (OK)")

        # 80. list_devices_for_policies (needs a policy uuid)
        if policy_uuid:
            resp = await _safe_call(
                session, "list_devices_for_policies", {"policies": [policy_uuid]}
            )
            record("list_devices_for_policies", resp is not None, _count_or_err(resp))
        else:
            record("list_devices_for_policies", True, "skipped — no policy uuid (OK)")

        # 81. policy_execution_counts
        resp = await _safe_call(session, "policy_execution_counts", {})
        record("policy_execution_counts", resp is not None, _data_keys(resp))

        # 82. policy_run_detail_v2 (needs policy_uuid + exec_token)
        if policy_uuid and exec_token:
            resp = await _safe_call(
                session,
                "policy_run_detail_v2",
                {"policy_uuid": policy_uuid, "exec_token": exec_token, "limit": 2},
            )
            record("policy_run_detail_v2", resp is not None, _count_or_err(resp))
        else:
            record(
                "policy_run_detail_v2",
                True,
                f"skipped — policy_uuid={policy_uuid}, exec_token={exec_token} (OK)",
            )

        # ---- Vuln Sync action-set detail (need an action set to exist) ----
        log.info(f"\n{BOLD}Phase 4: Vuln Sync action-set detail{RESET}")
        resp = await _safe_call(session, "list_remediation_action_sets", {})
        action_sets = _extract_list(resp.get("data")) if resp else []
        action_set_id = _extract_id(action_sets[0], "id", "action_set_id") if action_sets else None

        # 83. get_action_set_detail
        if action_set_id:
            resp = await _safe_call(
                session, "get_action_set_detail", {"action_set_id": action_set_id}
            )
            record("get_action_set_detail", resp is not None, _data_keys(resp))
        else:
            record("get_action_set_detail", True, "skipped — no action sets (OK)")

        # 84. get_action_set_issues
        if action_set_id:
            resp = await _safe_call(
                session, "get_action_set_issues", {"action_set_id": action_set_id}
            )
            record("get_action_set_issues", resp is not None, _count_or_err(resp))
        else:
            record("get_action_set_issues", True, "skipped — no action sets (OK)")

        # 85. get_action_set_solutions
        if action_set_id:
            resp = await _safe_call(
                session, "get_action_set_solutions", {"action_set_id": action_set_id}
            )
            record("get_action_set_solutions", resp is not None, _count_or_err(resp))
        else:
            record("get_action_set_solutions", True, "skipped — no action sets (OK)")

        # ---- Other detail-by-id reads ----
        log.info(f"\n{BOLD}Phase 4: Misc detail-by-id{RESET}")

        # 86. get_data_extract (needs an extract id)
        resp = await _safe_call(session, "list_data_extracts", {})
        extracts = _extract_list(resp.get("data")) if resp else []
        extract_id = _extract_id(extracts[0], "id", "extract_id") if extracts else None
        if extract_id:
            resp = await _safe_call(session, "get_data_extract", {"extract_id": extract_id})
            record("get_data_extract", resp is not None, f"id={extract_id}")
        else:
            record("get_data_extract", True, "skipped — no data extracts (OK)")

        # 87. get_webhook (needs a webhook id)
        resp = await _safe_call(session, "list_webhooks", {})
        webhooks = _extract_list(resp.get("data")) if resp else []
        webhook_id = None
        if webhooks:
            webhook_id = webhooks[0].get("id") or webhooks[0].get("webhook_id")
        if webhook_id:
            resp = await _safe_call(session, "get_webhook", {"webhook_id": webhook_id})
            record("get_webhook", resp is not None, f"id={webhook_id}")
            resp = await _safe_call(
                session, "list_webhook_deliveries", {"webhook_id": webhook_id, "limit": 5}
            )
            record("list_webhook_deliveries", resp is not None, _count_or_err(resp))
        else:
            record("get_webhook", True, "skipped — no webhooks in org (OK)")
            record("list_webhook_deliveries", True, "skipped — no webhooks in org (OK)")

        # ---- Splashtop read-only status ----
        log.info(f"\n{BOLD}Phase 4: Splashtop status (read-only){RESET}")

        # 88. splashtop_device_status
        if device_uuid:
            resp = await _safe_call(
                session, "splashtop_device_status", {"device_uuid": device_uuid}
            )
            record("splashtop_device_status", resp is not None, _data_keys(resp))
        else:
            record("splashtop_device_status", True, "skipped — no device uuid (OK)")

        # 89. splashtop_session_status
        if device_uuid:
            resp = await _safe_call(
                session, "splashtop_session_status", {"device_uuid": device_uuid}
            )
            record("splashtop_session_status", resp is not None, _data_keys(resp))
        else:
            record("splashtop_session_status", True, "skipped — no device uuid (OK)")

        # 90. splashtop_get_attended_access
        if device_uuid:
            resp = await _safe_call(
                session, "splashtop_get_attended_access", {"device_uuid": device_uuid}
            )
            record("splashtop_get_attended_access", resp is not None, _data_keys(resp))
        else:
            record("splashtop_get_attended_access", True, "skipped — no device uuid (OK)")

        # ---- #111 update_device (safe no-op write) ----
        log.info(f"\n{BOLD}Phase 4: update_device (#111, no-op write){RESET}")

        # 91. update_device — re-apply the device's CURRENT custom_name so the
        # write is a genuine no-op (no state change). Skip-OK if the device has
        # no custom_name to echo back, to avoid mutating live state.
        current_name = None
        if device_id:
            detail = await _safe_call(session, "device_detail", {"device_id": device_id})
            if detail and isinstance(detail.get("data"), dict):
                current_name = detail["data"].get("custom_name")
        if device_id and current_name:
            resp = await _safe_call(
                session,
                "update_device",
                {
                    "device_id": device_id,
                    "custom_name": current_name,
                    "request_id": f"smoke-{uuid.uuid4()}",
                },
            )
            record("update_device (no-op)", resp is not None, f"custom_name={current_name!r}")
        else:
            record(
                "update_device (no-op)",
                True,
                "skipped — no device custom_name to echo (avoids live mutation) (OK)",
            )

        # 92. MCP App resources — verify the ui:// App surfaces boot and list with
        # the MCP-App MIME on a live server (#178–#182). The App plumbing is not
        # exercised by any tool call, so this resources/list check is its only live
        # coverage: it confirms the dependency-free ui:// + AppConfig path actually
        # registers in production, not just in unit introspection.
        _UI_MIME = "text/html;profile=mcp-app"
        _EXPECTED_APP_RESOURCES = {
            "ui://automox/triage.html",
            "ui://automox/patch-approval.html",
            "ui://automox/policy-blast-radius.html",
            "ui://automox/remediation-apply.html",
            "ui://automox/access-certification.html",
        }
        try:
            res_result = await session.list_resources()
            by_uri = {str(r.uri): getattr(r, "mimeType", None) for r in res_result.resources}
            missing = sorted(_EXPECTED_APP_RESOURCES - set(by_uri))
            bad_mime = sorted(
                u for u in _EXPECTED_APP_RESOURCES & set(by_uri) if by_uri[u] != _UI_MIME
            )
            ok = not missing and not bad_mime
            detail = (
                f"{len(_EXPECTED_APP_RESOURCES)} App resources list with MCP-App MIME"
                if ok
                else f"missing={missing} bad_mime={bad_mime}"
            )
            record("mcp_app_resources", ok, detail)
        except Exception as exc:
            record("mcp_app_resources", False, str(exc))


def _extract_id(item: dict[str, Any], *keys: str) -> int | None:
    """Try multiple field names to extract an ID from a response item."""
    for key in keys:
        val = item.get(key)
        if val is not None:
            return int(val)
    return None


def _extract_list(data: Any) -> list[dict[str, Any]]:
    """Extract the primary list from a tool response data field.

    Data can be:
      - A plain list: [...]
      - A dict wrapping a list: {"devices": [...], "total_devices_returned": N}
    This helper finds the first list value in either case.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for val in data.values():
            if isinstance(val, list):
                return val
    return []


# Sentinel returned by _safe_call when a tool fails with a status the caller
# declared tolerable (e.g. 403/404 on account-admin tools the smoke key isn't
# scoped for). The caller records skip-OK rather than FAIL, so a limited key
# doesn't make the pre-tag gate noisy.
_TOLERATED = object()


# Substrings that mark a transient upstream blip (connection reset/refused
# before headers, gateway disconnect) rather than a real tool failure. The
# Automox gateway intermittently resets connections; retrying briefly rides it
# out. Without this, a network hiccup fails the pre-tag gate on an unrelated
# tool and the run looks broken when nothing is.
_TRANSIENT_MARKERS = (
    "connect error",
    "connection refused",
    "disconnect/reset before headers",
    "remote connection failure",
    "transport failure",
)


async def _safe_call(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any],
    *,
    retries: int = 2,
    tolerate: tuple[int, ...] = (),
) -> dict[str, Any] | None | object:
    """Call a tool, returning None on any exception (the caller records the failure).

    Retries on rate-limit errors (60s pause) and on transient upstream
    connection resets (short pause). If the tool errors with an HTTP status in
    ``tolerate``, returns the ``_TOLERATED`` sentinel (the caller records
    skip-OK) instead of None.
    """
    for attempt in range(1 + retries):
        try:
            result = await session.call_tool(name, arguments=arguments)
            if result.isError:
                text = _collect_text(result)
                low = text.lower()
                if attempt < retries and any(m in low for m in _TRANSIENT_MARKERS):
                    log.info(f"    transient on {name}, retrying in 3s…")
                    await asyncio.sleep(3)
                    continue
                if "rate limit" in low and attempt < retries:
                    log.info(f"    rate-limited on {name}, waiting 60s…")
                    await asyncio.sleep(60)
                    continue
                if any(f"status={code}" in text for code in tolerate):
                    log.info(f"    {YELLOW}skip-OK{RESET} {name}: tolerated — {text[:120]}")
                    return _TOLERATED
                log.warning(f"    {YELLOW}WARN{RESET} {name}: tool error — {text[:200]}")
                return None
            return _parse_tool_result(result)
        except Exception as exc:
            if attempt < retries and any(m in str(exc).lower() for m in _TRANSIENT_MARKERS):
                log.info(f"    transient on {name} ({exc}), retrying in 3s…")
                await asyncio.sleep(3)
                continue
            log.warning(f"    {YELLOW}WARN{RESET} {name}: {exc}")
            return None
    return None


def _collect_text(result: types.CallToolResult) -> str:
    """Join all text content blocks from a tool result."""
    parts = []
    for block in result.content:
        if isinstance(block, types.TextContent):
            parts.append(block.text)
    return "\n".join(parts)


def _parse_tool_result(result: types.CallToolResult) -> dict[str, Any]:
    """Parse the JSON response from a tool call.

    Handles both single text blocks and multiple blocks (some tools
    return the main response in the first block with extra info in later blocks).
    Also handles concatenated JSON objects in a single block.
    """
    for block in result.content:
        if isinstance(block, types.TextContent):
            text = block.text.strip()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                # Try parsing just the first JSON object (handles concatenated JSON)
                decoder = json.JSONDecoder()
                try:
                    obj, _ = decoder.raw_decode(text)
                    if isinstance(obj, dict):
                        return obj
                except (json.JSONDecodeError, ValueError):
                    continue
    raise ValueError("No parseable JSON in tool result")


def _count_or_err(resp: dict[str, Any] | None) -> str:
    if resp is None:
        return "call failed"
    data = resp.get("data")
    if isinstance(data, list):
        return f"count={len(data)}"
    return f"data type={type(data).__name__}"


def _data_keys(resp: dict[str, Any] | None) -> str:
    if resp is None:
        return "call failed"
    data = resp.get("data")
    if isinstance(data, dict):
        keys = list(data.keys())[:6]
        return f"keys={keys}"
    if isinstance(data, list):
        return f"list len={len(data)}"
    return f"type={type(data).__name__}"


# ===================================================================
#  Main
# ===================================================================


def main() -> int:
    check_prereqs()

    log.info(f"{BOLD}{'=' * 60}{RESET}")
    log.info(f"  {BOLD}Automox MCP — Production Smoke Tests{RESET}")
    log.info(f"{BOLD}{'=' * 60}{RESET}")

    # 1. Stdio startup (synchronous)
    test_stdio_startup()

    # 2–6, 8–55: HTTP transport tests (async)
    asyncio.run(run_http_tests())

    # 7. Non-loopback warning (separate server, synchronous)
    test_non_loopback_warning()

    return summary()


if __name__ == "__main__":
    sys.exit(main())

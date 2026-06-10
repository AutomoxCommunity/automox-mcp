"""Tests for discover_capabilities meta-tool.

Two layers:

- StubServer tests — the original lightweight checks, which now also exercise
  the no-introspection fallback (a server without ``local_provider`` gets no
  availability annotations).
- Real-FastMCP tests — register the full tool set under different gate / mode /
  module configurations and assert discovery output matches the registered set
  (#217): the static catalog must not silently diverge from the callable
  registry.
"""

from __future__ import annotations

import tempfile
from typing import Any

import pytest
from conftest import StubClient
from fastmcp import FastMCP

from automox_mcp.tools import _get_tool_names, register_tools
from automox_mcp.tools.meta_tools import (
    _ALIAS_DOMAINS,
    _DOMAIN_CATALOG,
    _GATED_TOOLS,
    register,
)


class StubServer:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, name: str, description: str = "", **kwargs):
        def decorator(func):
            self.tools[name] = func
            return func

        return decorator


class FakeClient:
    org_id = 42
    org_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    account_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture
def server():
    s = StubServer()
    register(s, read_only=False, client=FakeClient())
    return s


# ---------------------------------------------------------------------------
# StubServer (no FastMCP internals → no availability annotations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_capabilities_valid_domain(server):
    result = await server.tools["discover_capabilities"](domain="devices")
    data = result["data"]
    assert data["domain"] == "devices"
    assert data["tool_count"] > 0
    assert isinstance(data["tools"], list)
    assert data["tools"][0]["name"] == "list_devices"


@pytest.mark.asyncio
async def test_discover_capabilities_unknown_domain(server):
    result = await server.tools["discover_capabilities"](domain="nonexistent")
    data = result["data"]
    assert "error" in data
    assert "available_domains" in data


@pytest.mark.asyncio
async def test_discover_capabilities_no_domain_lists_all(server):
    result = await server.tools["discover_capabilities"]()
    data = result["data"]
    assert "available_domains" in data
    assert "devices" in data["available_domains"]
    assert "policies" in data["available_domains"]


@pytest.mark.asyncio
async def test_discover_capabilities_case_insensitive(server):
    result = await server.tools["discover_capabilities"](domain="DEVICES")
    assert result["data"]["domain"] == "devices"


@pytest.mark.asyncio
async def test_stub_server_omits_availability(server):
    """Without FastMCP internals, availability is unknown and must be omitted."""
    result = await server.tools["discover_capabilities"](domain="devices")
    assert all("available" not in t for t in result["data"]["tools"])
    no_arg = await server.tools["discover_capabilities"]()
    assert "registered_tool_count" not in no_arg["data"]
    assert "unavailable_tools" not in no_arg["data"]


# ---------------------------------------------------------------------------
# Catalog shape
# ---------------------------------------------------------------------------


def test_all_domains_present():
    expected = {
        "devices",
        "device_search",
        "policies",
        "policy_history",
        "patches",
        "groups",
        "events",
        "reports",
        "audit",
        "webhooks",
        "worklets",
        "data_extracts",
        "vuln_sync",
        "account",
        "compound",
        "policy_windows",
        "splashtop",
    }
    assert set(_DOMAIN_CATALOG.keys()) == expected


def test_catalog_entries_are_tuples_of_name_and_description():
    for domain, tools in _DOMAIN_CATALOG.items():
        for entry in tools:
            assert isinstance(entry, tuple), f"Bad entry in {domain}"
            assert len(entry) == 2, f"Bad entry in {domain}: {entry}"
            name, desc = entry
            assert isinstance(name, str) and name
            assert isinstance(desc, str) and desc


def test_alias_domains_are_fully_cross_listed():
    """Every tool in an alias domain must have a home in a non-alias domain."""
    for alias in _ALIAS_DOMAINS:
        home_names = {
            name
            for domain, tools in _DOMAIN_CATALOG.items()
            if domain not in _ALIAS_DOMAINS
            for name, _ in tools
        }
        for name, _ in _DOMAIN_CATALOG[alias]:
            assert name in home_names, f"{name} in alias domain {alias} has no home domain"


# ---------------------------------------------------------------------------
# Real FastMCP — discovery must match the registered set (#217)
# ---------------------------------------------------------------------------

# Env vars that influence which tools register; cleared so tests are
# independent of the ambient shell (mirrors tests/test_doc_tool_counts.py).
_GATING_ENV = (
    "AUTOMOX_MCP_READ_ONLY",
    "AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS",
    "AUTOMOX_MCP_ALLOW_SPLASHTOP_BULK_INSTALL_UNINSTALL",
    "AUTOMOX_MCP_ALLOW_DELETE_DEVICE",
    "AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE",
    "AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS",
    "AUTOMOX_MCP_TRANSPORT",
    "AUTOMOX_MCP_MODULES",
    "AUTOMOX_MCP_TOOL_PREFIX",
)

# The gate env vars come from the mapping under test, so the two can't drift.
_FULL_GATES = {env: "true" for env in _GATED_TOOLS.values()} | {
    "AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS": tempfile.gettempdir(),
}


def _register_full(monkeypatch: pytest.MonkeyPatch, **env: str) -> FastMCP:
    for key in _GATING_ENV:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    server = FastMCP("discover-test")
    register_tools(server, client=StubClient())
    return server


def _discover_fn(server: FastMCP):
    lp = server.local_provider
    for key, comp in lp._components.items():
        if key.startswith("tool:") and comp.name.endswith("discover_capabilities"):
            return comp.fn
    raise AssertionError("discover_capabilities not registered")


async def _availability(server: FastMCP) -> dict[str, bool]:
    """Map every catalogued tool to its discovery-reported availability."""
    fn = _discover_fn(server)
    out: dict[str, bool] = {}
    for domain in _DOMAIN_CATALOG:
        result = await fn(domain=domain)
        for tool in result["data"]["tools"]:
            out[tool["name"]] = tool["available"]
    return out


def test_gated_tools_mapping_matches_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    """_GATED_TOOLS is hand-maintained; the registry is the source of truth."""
    full = _get_tool_names(_register_full(monkeypatch, **_FULL_GATES))
    default = _get_tool_names(_register_full(monkeypatch))
    assert full - default == set(_GATED_TOOLS), (
        "meta_tools._GATED_TOOLS drifted from the gate-controlled registration diff"
    )


@pytest.mark.asyncio
async def test_full_gates_everything_available(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _register_full(monkeypatch, **_FULL_GATES)
    availability = await _availability(server)
    unavailable = sorted(n for n, ok in availability.items() if not ok)
    assert unavailable == []

    no_arg = (await _discover_fn(server)())["data"]
    assert "unavailable_tools" not in no_arg
    # Registered set = catalog uniques + discover_capabilities itself.
    assert no_arg["registered_tool_count"] == no_arg["unique_tool_count"] + 1


@pytest.mark.asyncio
async def test_gates_off_marks_gated_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _register_full(monkeypatch)
    availability = await _availability(server)
    unavailable = {n for n, ok in availability.items() if not ok}
    assert unavailable == set(_GATED_TOOLS)

    no_arg = (await _discover_fn(server)())["data"]
    assert sorted(no_arg["unavailable_tools"]) == sorted(_GATED_TOOLS)


@pytest.mark.asyncio
async def test_gated_entries_always_name_their_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _register_full(monkeypatch, **_FULL_GATES)
    fn = _discover_fn(server)
    seen: dict[str, str] = {}
    for domain in _DOMAIN_CATALOG:
        result = await fn(domain=domain)
        for tool in result["data"]["tools"]:
            if "gated_by" in tool:
                seen[tool["name"]] = tool["gated_by"]
    assert seen == _GATED_TOOLS


@pytest.mark.asyncio
async def test_read_only_marks_write_tools_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _register_full(monkeypatch, AUTOMOX_MCP_READ_ONLY="true")
    registered = _get_tool_names(server)
    availability = await _availability(server)
    # Discovery's availability must equal registry membership, tool by tool.
    assert availability == {n: n in registered for n in availability}
    assert availability["list_devices"] is True
    assert availability["delete_policy"] is False

    no_arg = (await _discover_fn(server)())["data"]
    assert no_arg["registered_tool_count"] == len(registered)
    assert set(no_arg["unavailable_tools"]) == {n for n, ok in availability.items() if not ok}


@pytest.mark.asyncio
async def test_modules_filter_marks_unloaded_domains_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _register_full(monkeypatch, AUTOMOX_MCP_MODULES="devices")
    fn = _discover_fn(server)
    webhooks = (await fn(domain="webhooks"))["data"]["tools"]
    assert all(t["available"] is False for t in webhooks)
    devices = (await fn(domain="devices"))["data"]["tools"]
    assert any(t["available"] for t in devices)


@pytest.mark.asyncio
async def test_tool_prefix_does_not_break_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _register_full(monkeypatch, AUTOMOX_MCP_TOOL_PREFIX="ax", **_FULL_GATES)
    assert "ax_list_devices" in _get_tool_names(server)
    availability = await _availability(server)
    assert availability["list_devices"] is True


@pytest.mark.asyncio
async def test_no_arg_self_check_totals(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _register_full(monkeypatch, **_FULL_GATES)
    data = (await _discover_fn(server)(list_all_tools=True))["data"]

    assert data["domain_tool_counts"] == {d: len(t) for d, t in _DOMAIN_CATALOG.items()}
    assert data["alias_domains"] == sorted(_ALIAS_DOMAINS)
    # Cross-listed = names appearing in two domains; the naive sum minus the
    # unique count must equal the number of cross-listed tools.
    naive_sum = sum(data["domain_tool_counts"].values())
    assert naive_sum - data["unique_tool_count"] == len(data["cross_listed_tools"])
    assert "discover_capabilities" in data["note"]

    all_tools = data["all_tools"]
    assert len(all_tools) == data["unique_tool_count"]
    assert len(set(all_tools)) == len(all_tools)
    assert all_tools == sorted(all_tools)
    assert "discover_capabilities" not in all_tools


@pytest.mark.asyncio
async def test_per_domain_alias_and_cross_listed_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _register_full(monkeypatch, **_FULL_GATES)
    fn = _discover_fn(server)

    compound = (await fn(domain="compound"))["data"]
    assert compound["alias_domain"] is True
    assert all(t["cross_listed"] is True for t in compound["tools"])

    patches = (await fn(domain="patches"))["data"]
    assert "alias_domain" not in patches
    flags = {t["name"]: t.get("cross_listed", False) for t in patches["tools"]}
    assert flags["prepatch_report"] is True
    assert flags["list_device_packages"] is False

"""Guard against tool-count drift between code and the hand-maintained docs.

The tool counts in ``README.md``, ``mcpb/manifest.json``, and
``docs/tool-reference.md`` are maintained by hand and have drifted before
(prompting the 1.2.1 fixup). These tests assert each documented count and the
documented per-domain breakdown match the *actually registered* tool set, so a
future tool addition/removal that forgets a doc update fails CI instead of
shipping a wrong number (#113).

The **"N MCP resources"** count in ``docs/tool-reference.md`` and
``mcpb/manifest.json`` is guarded the same way (real-FastMCP resource
introspection) — closing the previously-silent resource-count drift now that
``ui://`` MCP App resources exist. The resource-table *row* and the ``### MCP
Apps`` note remain manual (not derivable from a count).

The source of truth is the registered server, read under three gate
configurations:

- **full** — write mode + both opt-in env gates → every tool (matches the
  "N tools" headline the docs advertise).
- **read-only** — ``AUTOMOX_MCP_READ_ONLY`` → the read tools only.
- write count is ``full - read``.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest
from conftest import StubClient
from fastmcp import FastMCP

from automox_mcp.resources import register_resources
from automox_mcp.tools import _get_tool_names, register_tools

_REPO_ROOT = Path(__file__).resolve().parent.parent
_README = _REPO_ROOT / "README.md"
_MANIFEST = _REPO_ROOT / "mcpb" / "manifest.json"
_TOOL_REFERENCE = _REPO_ROOT / "docs" / "tool-reference.md"

# Env vars that influence which tools register; cleared so the test is
# independent of the ambient shell.
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

# upload_policy_file registers only with a non-empty, existing allowlist dir.
_TMP_DIR = tempfile.gettempdir()

# The opt-in gate flags the "full" configuration must set so every gated tool
# registers (matches the "N tools" headline the docs advertise).
_FULL_GATES = {
    "AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS": "true",
    "AUTOMOX_MCP_ALLOW_SPLASHTOP_BULK_INSTALL_UNINSTALL": "true",
    "AUTOMOX_MCP_ALLOW_DELETE_DEVICE": "true",
    "AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE": "true",
    "AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS": _TMP_DIR,
}


def _register(monkeypatch: pytest.MonkeyPatch, **env: str) -> set[str]:
    """Register every module against a fresh server and return the tool names."""
    for key in _GATING_ENV:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    server = FastMCP("count-test")
    register_tools(server, client=StubClient())
    return _get_tool_names(server)


@pytest.fixture
def registered_counts(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Tool counts under the full / read-only gate configurations."""
    full = _register(monkeypatch, **_FULL_GATES)
    read_only = _register(monkeypatch, AUTOMOX_MCP_READ_ONLY="true")
    return {
        "total": len(full),
        "read": len(read_only),
        "write": len(full) - len(read_only),
    }


def _full_tool_names(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    return _register(monkeypatch, **_FULL_GATES)


# ---------------------------------------------------------------------------
# tool-reference.md
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^## (?P<name>.+?) \((?P<count>\d+) tools?\)", re.M)
_BULLET_RE = re.compile(r"^- \*\*`(?P<name>[a-z0-9_]+)`\*\*", re.M)
_HEADER_TOTAL_RE = re.compile(r"for all (?P<count>\d+) tools")


def _parse_tool_sections() -> list[tuple[str, int, list[str]]]:
    """Return (section_name, declared_count, [tool_names]) for each tool section.

    A "tool section" is a ``## Name (N tools)`` heading; the bullet list runs
    until the next ``## `` heading. The Workflow Prompts section (``(6 prompts)``)
    and prose sections (Pagination, etc.) are naturally excluded — they don't
    match the ``(N tools)`` heading pattern.
    """
    lines = _TOOL_REFERENCE.read_text().splitlines()
    sections: list[tuple[str, int, list[str]]] = []
    cur_name: str | None = None
    cur_count = 0
    cur_tools: list[str] = []

    def _flush() -> None:
        if cur_name is not None:
            sections.append((cur_name, cur_count, cur_tools.copy()))

    for line in lines:
        header = _SECTION_RE.match(line)
        if header:
            _flush()
            cur_name = header.group("name")
            cur_count = int(header.group("count"))
            cur_tools = []
            continue
        if line.startswith("## "):
            # A non-tool heading closes the current tool section.
            _flush()
            cur_name = None
            cur_count = 0
            cur_tools = []
            continue
        if cur_name is not None:
            bullet = _BULLET_RE.match(line)
            if bullet:
                cur_tools.append(bullet.group("name"))
    _flush()
    return sections


def test_tool_reference_header_total(monkeypatch: pytest.MonkeyPatch) -> None:
    total = len(_full_tool_names(monkeypatch))
    text = _TOOL_REFERENCE.read_text()
    match = _HEADER_TOTAL_RE.search(text)
    assert match, "could not find 'for all N tools' in docs/tool-reference.md"
    assert int(match.group("count")) == total, (
        f"docs/tool-reference.md header says {match.group('count')} tools, "
        f"registered (all gates) = {total}"
    )


def test_tool_reference_section_counts_match_bullets() -> None:
    mismatches = [
        (name, declared, len(tools))
        for name, declared, tools in _parse_tool_sections()
        if declared != len(tools)
    ]
    assert not mismatches, (
        "tool-reference.md section headers disagree with their bullet counts "
        f"(section, declared, actual): {mismatches}"
    )


def test_tool_reference_documents_exactly_registered_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered = _full_tool_names(monkeypatch)
    documented: set[str] = set()
    for _name, _count, tools in _parse_tool_sections():
        documented.update(tools)
    assert documented == registered, (
        f"documented-but-not-registered: {sorted(documented - registered)}; "
        f"registered-but-not-documented: {sorted(registered - documented)}"
    )


# ---------------------------------------------------------------------------
# discover_capabilities catalog (meta_tools._DOMAIN_CATALOG)
# ---------------------------------------------------------------------------

# `discover_capabilities` is intentionally absent from every domain — you can't
# discover the discovery tool through itself. Every *other* registered tool must
# appear, or the model-facing capability directory silently drifts from reality.
_CATALOG_EXCLUDED = {"discover_capabilities"}


def test_discover_catalog_matches_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    from automox_mcp.tools.meta_tools import _DOMAIN_CATALOG

    registered = _full_tool_names(monkeypatch)
    catalog = {name for tools in _DOMAIN_CATALOG.values() for name, _ in tools}

    # No phantom entries: every catalogued name must be a real registered tool.
    assert catalog - registered == set(), (
        f"discover_capabilities catalog lists unregistered tools: {sorted(catalog - registered)}"
    )
    # Completeness: every registered tool except the discovery meta-tool must be
    # discoverable through the catalog.
    missing = (registered - catalog) - _CATALOG_EXCLUDED
    assert registered - catalog == _CATALOG_EXCLUDED, (
        f"registered tools missing from the discover_capabilities catalog: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# README.md
# ---------------------------------------------------------------------------


def test_readme_counts(registered_counts: dict[str, int]) -> None:
    text = _README.read_text()
    total, read, write = (
        registered_counts["total"],
        registered_counts["read"],
        registered_counts["write"],
    )

    # "The server exposes N tools" / "all N tools"
    totals = {int(n) for n in re.findall(r"(?:exposes|all) (\d+) tools", text)}
    assert totals == {total}, f"README total-tool mentions {totals}, expected {{{total}}}"

    # "(84 of N tools remain)" — the read/total pair must agree on both numbers.
    of_pairs = {(int(a), int(b)) for a, b in re.findall(r"(\d+) of (\d+) tools?", text)}
    assert of_pairs == {(read, total)}, (
        f"README 'X of Y tools' pairs {of_pairs}, expected {{({read}, {total})}}"
    )

    # "all N write tools" / "all N write operations"
    write_mentions = {int(n) for n in re.findall(r"all (\d+) write", text)}
    assert write_mentions == {write}, (
        f"README write-tool mentions {write_mentions}, expected {{{write}}}"
    )


# ---------------------------------------------------------------------------
# mcpb/manifest.json
# ---------------------------------------------------------------------------


def test_manifest_counts(registered_counts: dict[str, int]) -> None:
    manifest = json.loads(_MANIFEST.read_text())
    total, read, write = (
        registered_counts["total"],
        registered_counts["read"],
        registered_counts["write"],
    )

    long_desc = manifest["long_description"]
    desc_total = re.search(r"Exposes (\d+) MCP tools", long_desc)
    assert desc_total and int(desc_total.group(1)) == total, (
        f"manifest long_description tool count != {total}"
    )

    # read-only config description: "Disable all 46 write operations. 84 read tools…"
    blob = json.dumps(manifest)
    write_mentions = {int(n) for n in re.findall(r"all (\d+) write operations", blob)}
    assert write_mentions == {write}, (
        f"manifest write-operation mentions {write_mentions}, expected {{{write}}}"
    )
    read_mentions = {int(n) for n in re.findall(r"(\d+) read tools", blob)}
    assert read_mentions == {read}, (
        f"manifest read-tool mentions {read_mentions}, expected {{{read}}}"
    )


# ---------------------------------------------------------------------------
# MCP resource count (incl. ui:// App resources) — mirrors the tool guard
# ---------------------------------------------------------------------------


def _registered_resource_count() -> int:
    """Count registered MCP resources on a real FastMCP server.

    Resources aren't gated, so no env configuration is needed — just build a
    server, register every resource, and count the ``resource:`` components
    (the same ``local_provider._components`` introspection ``_get_tool_names``
    uses for tools).
    """
    server = FastMCP("resource-count-test")
    register_resources(server, client=StubClient())
    return sum(1 for key in server.local_provider._components if key.startswith("resource:"))


def test_tool_reference_resource_count() -> None:
    count = _registered_resource_count()
    match = re.search(r"exposes (\d+) MCP resources", _TOOL_REFERENCE.read_text())
    assert match, "could not find 'exposes N MCP resources' in docs/tool-reference.md"
    assert int(match.group(1)) == count, (
        f"docs/tool-reference.md says {match.group(1)} MCP resources, registered = {count}"
    )


def test_manifest_resource_count() -> None:
    count = _registered_resource_count()
    long_desc = json.loads(_MANIFEST.read_text())["long_description"]
    match = re.search(r"(\d+) MCP resources", long_desc)
    assert match, "could not find 'N MCP resources' in mcpb/manifest.json long_description"
    assert int(match.group(1)) == count, (
        f"mcpb/manifest.json says {match.group(1)} MCP resources, registered = {count}"
    )


# ---------------------------------------------------------------------------
# mcpb/manifest.json tools[] / prompts[] — Claude Desktop's "Tools"/"Prompts"
# details sections. Generated by scripts/generate_mcpb_catalog.py; these tests
# fail CI when the tool/prompt set changes without a regeneration.
# ---------------------------------------------------------------------------


def test_manifest_tools_match_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = json.loads(_MANIFEST.read_text())
    registered = _full_tool_names(monkeypatch)
    listed = [t["name"] for t in manifest["tools"]]

    assert len(set(listed)) == len(listed), "duplicate names in manifest tools[]"
    assert set(listed) == registered, (
        "mcpb/manifest.json tools[] drifted from the registered set — "
        "re-run scripts/generate_mcpb_catalog.py. "
        f"listed-not-registered: {sorted(set(listed) - registered)}; "
        f"registered-not-listed: {sorted(registered - set(listed))}"
    )
    # Everything is listed, so nothing extra is "generated".
    assert manifest["tools_generated"] is False


def test_manifest_tool_descriptions_match_catalog() -> None:
    from automox_mcp.tools.meta_tools import _DOMAIN_CATALOG

    catalog: dict[str, str] = {}
    for tools in _DOMAIN_CATALOG.values():
        for name, desc in tools:
            catalog.setdefault(name, desc)  # first occurrence wins (generator rule)

    for entry in json.loads(_MANIFEST.read_text())["tools"]:
        expected = catalog.get(entry["name"])
        if expected is None:  # discover_capabilities — description lives in the generator
            assert entry["description"], f"{entry['name']}: empty manifest description"
            continue
        assert entry["description"] == expected, (
            f"{entry['name']}: manifest description drifted from the discover_capabilities "
            "catalog — re-run scripts/generate_mcpb_catalog.py"
        )


def test_manifest_prompts_match_registered() -> None:
    from automox_mcp.prompts import register_prompts

    server = FastMCP("prompt-count-test")
    register_prompts(server)
    registered = {
        comp.name: ([a.name for a in (comp.arguments or [])], comp.description)
        for key, comp in server.local_provider._components.items()
        if key.startswith("prompt:")
    }

    manifest = json.loads(_MANIFEST.read_text())
    listed = {p["name"]: p for p in manifest["prompts"]}
    assert set(listed) == set(registered), (
        "mcpb/manifest.json prompts[] drifted from the registered prompts — "
        "re-run scripts/generate_mcpb_catalog.py. "
        f"listed-not-registered: {sorted(set(listed) - set(registered))}; "
        f"registered-not-listed: {sorted(set(registered) - set(listed))}"
    )
    for name, (arguments, description) in registered.items():
        entry = listed[name]
        assert entry.get("arguments", []) == arguments, f"{name}: arguments drifted"
        assert entry["description"] == description, f"{name}: description drifted"
        assert entry["text"], f"{name}: text is required by the MCPB schema"
    assert manifest["prompts_generated"] is False

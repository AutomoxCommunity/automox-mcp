"""Tests for upload_policy_file: workflow, registration gating, and dispatch."""

from __future__ import annotations

from typing import cast

import pytest
from conftest import FakeClient, StubClient, StubServer

from automox_mcp.client import AutomoxClient
from automox_mcp.tools import policy_tools
from automox_mcp.workflows.policy_crud import upload_policy_file


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE",
        "AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS",
        "AUTOMOX_MCP_UPLOAD_MAX_BYTES",
        "AUTOMOX_MCP_UPLOAD_TIMEOUT_SECONDS",
        "AUTOMOX_MCP_TRANSPORT",
        "AUTOMOX_MCP_READ_ONLY",
    ):
        monkeypatch.delenv(key, raising=False)


def _installer(tmp_path) -> str:
    f = tmp_path / "setup.msi"
    f.write_bytes(b"MZ\x90\x00binary-installer-bytes")
    return str(f)


# ---------------------------------------------------------------------------
# workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_streams_file_and_omits_o_for_main_org(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS", str(tmp_path))
    path = _installer(tmp_path)
    client = StubClient(post_responses={"/policies/12/files": [{}]})

    result = await upload_policy_file(
        cast(AutomoxClient, client), org_id=None, policy_id=12, file_path=path
    )

    method, call_path, payload = client.calls[0]
    assert method == "POST_MULTIPART"
    assert call_path == "/policies/12/files"
    # No `o` query param for the main org.
    assert payload["params"] is None
    fname, _handle, ctype = payload["files"]["file"]
    assert fname == "setup.msi"
    assert ctype == "application/octet-stream"
    assert result["data"]["uploaded"] is True
    assert result["data"]["policy_id"] == 12
    assert result["data"]["size_bytes"] > 0


@pytest.mark.asyncio
async def test_workflow_sends_o_for_child_org(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS", str(tmp_path))
    path = _installer(tmp_path)
    client = StubClient(post_responses={"/policies/9/files": [{}]})

    await upload_policy_file(cast(AutomoxClient, client), org_id=555, policy_id=9, file_path=path)

    _method, _path, payload = client.calls[0]
    assert payload["params"] == {"o": 555}


@pytest.mark.asyncio
async def test_workflow_rejects_path_outside_allowlist(tmp_path, monkeypatch) -> None:
    allowed = tmp_path / "ok"
    allowed.mkdir()
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS", str(allowed))
    outside = tmp_path / "evil.msi"
    outside.write_bytes(b"x")
    client = StubClient()

    with pytest.raises(ValueError, match="outside the allowed"):
        await upload_policy_file(cast(AutomoxClient, client), policy_id=1, file_path=str(outside))
    # Nothing was uploaded.
    assert client.calls == []


# ---------------------------------------------------------------------------
# registration gating
# ---------------------------------------------------------------------------


def _register(tmp_path, monkeypatch, *, read_only=False, **env: str) -> StubServer:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    server = StubServer()
    policy_tools.register(server, read_only=read_only, client=FakeClient())
    return server


def test_not_registered_without_flag(tmp_path, monkeypatch) -> None:
    server = _register(tmp_path, monkeypatch, AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS=str(tmp_path))
    assert "upload_policy_file" not in server.tools


def test_registered_with_flag_allowlist_stdio_writes(tmp_path, monkeypatch) -> None:
    server = _register(
        tmp_path,
        monkeypatch,
        AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE="true",
        AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS=str(tmp_path),
    )
    assert "upload_policy_file" in server.tools


def test_not_registered_without_allowlist(tmp_path, monkeypatch) -> None:
    server = _register(tmp_path, monkeypatch, AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE="true")
    assert "upload_policy_file" not in server.tools


def test_not_registered_in_read_only(tmp_path, monkeypatch) -> None:
    server = _register(
        tmp_path,
        monkeypatch,
        read_only=True,
        AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE="true",
        AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS=str(tmp_path),
    )
    assert "upload_policy_file" not in server.tools


def test_not_registered_under_remote_transport(tmp_path, monkeypatch) -> None:
    server = _register(
        tmp_path,
        monkeypatch,
        AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE="true",
        AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS=str(tmp_path),
        AUTOMOX_MCP_TRANSPORT="http",
    )
    assert "upload_policy_file" not in server.tools


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_uploads(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE", "true")
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS", str(tmp_path))
    path = _installer(tmp_path)

    server = StubServer()
    policy_tools.register(server, read_only=False, client=FakeClient(org_id=42))

    result = await server.tools["upload_policy_file"](policy_id=7, file_path=path)
    assert result["data"]["uploaded"] is True
    assert result["data"]["filename"] == "setup.msi"

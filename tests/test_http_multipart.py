"""Tests for AutomoxClient.post_multipart (file uploads).

These use a real httpx.AsyncClient wired to a MockTransport — not the
StubAsyncClient — because the behavior under test is the genuine httpx
content-type handling: the client sets a default ``Content-Type:
application/json`` that would clobber the multipart boundary, and
``post_multipart`` must override it with the boundary httpx encodes.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from automox_mcp.client import AutomoxAPIError, AutomoxClient


def _mock_client(client: AutomoxClient, handler: Any) -> None:
    """Swap the client's transport for a MockTransport, keeping the json default."""
    client._http = httpx.AsyncClient(
        base_url="https://console.automox.com/api",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        transport=httpx.MockTransport(handler),
    )


@pytest.fixture(autouse=True)
def _creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOMOX_API_KEY", "test-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "abc-123")
    monkeypatch.delenv("AUTOMOX_ORG_ID", raising=False)


@pytest.mark.asyncio
async def test_post_multipart_overrides_json_content_type() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers.get("content-type")
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(201, json={"id": 1, "status": "building"})

    async with AutomoxClient(org_id=42) as client:
        await client._http.aclose()
        _mock_client(client, handler)
        result = await client.post_multipart(
            "/orgs/42/remediations/action-sets/upload",
            params={"source": "generic"},
            files={"file": ("export.csv", b"Hostname,CVE ID\nhost1,CVE-2021-1234\n", "text/csv")},
            data={"format": "generic"},
        )

    assert result == {"id": 1, "status": "building"}
    # The json default must NOT win — the boundary-bearing multipart CT does.
    assert captured["content_type"].startswith("multipart/form-data; boundary=")
    # source rides the query string.
    assert "source=generic" in captured["url"]
    # Body carries both the file part and the format field.
    assert b'name="file"; filename="export.csv"' in captured["body"]
    assert b'name="format"' in captured["body"]
    assert b"CVE-2021-1234" in captured["body"]


@pytest.mark.asyncio
async def test_post_multipart_raises_on_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"errors": {"file": ["bad csv"]}})

    async with AutomoxClient(org_id=42) as client:
        await client._http.aclose()
        _mock_client(client, handler)
        with pytest.raises(AutomoxAPIError):
            await client.post_multipart(
                "/orgs/42/remediations/action-sets/upload",
                params={"source": "generic"},
                files={"file": ("x.csv", b"bad", "text/csv")},
                data={"format": "generic"},
            )


@pytest.mark.asyncio
async def test_post_multipart_wraps_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    async with AutomoxClient(org_id=42) as client:
        await client._http.aclose()
        _mock_client(client, handler)
        with pytest.raises(AutomoxAPIError) as excinfo:
            await client.post_multipart(
                "/orgs/42/remediations/action-sets/upload",
                files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
                data={"format": "generic"},
            )
        assert excinfo.value.status_code == 0

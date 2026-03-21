import json
from typing import Any

import pytest

from automox_mcp.client import AutomoxAPIError, AutomoxClient, AutomoxRateLimitError


class StubResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        json_data: Any = None,
        text: str | None = None,
        json_error: bool = False,
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self._json_error = json_error
        self.content = b""
        if json_data is not None:
            self.content = json.dumps(json_data).encode("utf-8")
            if text is None:
                text = json.dumps(json_data)
        self.text = text or ""
        if not self.content and self.text:
            self.content = self.text.encode("utf-8")

    def json(self) -> Any:
        if self._json_error:
            raise json.JSONDecodeError("invalid json", self.text or "", 0)
        if self._json_data is None:
            raise json.JSONDecodeError("no data", "", 0)
        return self._json_data


class StubAsyncClient:
    instances: list["StubAsyncClient"] = []

    def __init__(
        self, *, base_url: str, headers: dict[str, str], timeout: Any, auth: Any = None
    ) -> None:
        self.base_url = base_url
        self.headers = headers
        self.timeout = timeout
        self.auth = auth
        self.calls: list[dict[str, Any]] = []
        self.responses: list[StubResponse] = []
        self.closed = False
        StubAsyncClient.instances.append(self)

    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
    ) -> StubResponse:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "params": params,
                "json": json,
                "headers": headers,
            }
        )
        if not self.responses:
            raise AssertionError("No stubbed responses available")
        return self.responses.pop(0)

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def reset_stubs(monkeypatch):
    StubAsyncClient.instances = []
    monkeypatch.setenv("AUTOMOX_API_KEY", "test-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "abc-123")
    monkeypatch.delenv("AUTOMOX_ORG_ID", raising=False)
    monkeypatch.setattr("automox_mcp.client.httpx.AsyncClient", StubAsyncClient)
    yield
    StubAsyncClient.instances = []


@pytest.mark.asyncio
async def test_get_success_uses_single_http_client():
    async with AutomoxClient(org_id=42) as client:
        (http_client,) = StubAsyncClient.instances
        http_client.responses = [StubResponse(json_data={"ok": True})]
        payload = await client.get("/foo")

    assert payload == {"ok": True}
    assert http_client.calls[0]["path"] == "/foo"
    # Auth is injected per-request via auth callback, not in shared headers
    assert "Authorization" not in http_client.headers
    assert http_client.auth is not None
    assert client._api_key == "test-key"


@pytest.mark.asyncio
async def test_get_raises_rate_limit():
    async with AutomoxClient(org_id=42) as client:
        (http_client,) = StubAsyncClient.instances
        http_client.responses = [
            StubResponse(status_code=429, json_data={"message": "slow down"})
        ]
        with pytest.raises(AutomoxRateLimitError):
            await client.get("/retry")


@pytest.mark.asyncio
async def test_get_raises_api_error_with_payload():
    async with AutomoxClient(org_id=42) as client:
        (http_client,) = StubAsyncClient.instances
        http_client.responses = [
            StubResponse(status_code=401, json_data={"message": "bad auth", "code": "unauthorized"})
        ]
        with pytest.raises(AutomoxAPIError) as exc:
            await client.get("/auth")

    assert exc.value.status_code == 401
    assert exc.value.payload["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_invalid_json_raises_api_error():
    async with AutomoxClient(org_id=42) as client:
        (http_client,) = StubAsyncClient.instances
        http_client.responses = [
            StubResponse(status_code=200, text="not json", json_error=True),
        ]

        with pytest.raises(AutomoxAPIError, match="invalid JSON"):
            await client.get("/foo")


# ---------------------------------------------------------------------------
# _bearer_auth callback (lines 107-108)
# ---------------------------------------------------------------------------


def test_bearer_auth_injects_authorization_header():
    """_bearer_auth must set the Authorization header on the request object."""
    import httpx

    client = AutomoxClient(api_key="my-token", account_uuid="acct-1")
    # Build a minimal real httpx.Request so we can inspect the headers
    request = httpx.Request("GET", "https://console.automox.com/api/orgs")
    modified = client._bearer_auth(request)
    assert modified is request
    assert modified.headers["Authorization"] == "Bearer my-token"


# ---------------------------------------------------------------------------
# _resolve_user_agent fallback (lines 27-28)
# ---------------------------------------------------------------------------


def test_resolve_user_agent_fallback_to_env_var(monkeypatch):
    """When the package is not installed, fall back to AUTOMOX_MCP_VERSION env var."""
    import importlib.metadata

    import automox_mcp.client as client_module

    monkeypatch.setenv("AUTOMOX_MCP_VERSION", "9.8.7")

    def raise_not_found(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", raise_not_found)

    ua = client_module._resolve_user_agent()
    assert ua == "automox-mcp/9.8.7"


def test_resolve_user_agent_fallback_default_when_no_env(monkeypatch):
    """When the package is not installed and AUTOMOX_MCP_VERSION is unset, use 0.0.0+dev."""
    import importlib.metadata

    import automox_mcp.client as client_module

    monkeypatch.delenv("AUTOMOX_MCP_VERSION", raising=False)

    def raise_not_found(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", raise_not_found)

    ua = client_module._resolve_user_agent()
    assert ua == "automox-mcp/0.0.0+dev"


# ---------------------------------------------------------------------------
# Async context manager __aenter__ / __aexit__ (lines 107-108)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aenter_returns_client_and_aexit_closes():
    """__aenter__ returns the client itself; __aexit__ closes the underlying HTTP client."""
    client = AutomoxClient(org_id=42)
    (http_client,) = StubAsyncClient.instances

    returned = await client.__aenter__()
    assert returned is client
    assert not http_client.closed

    await client.__aexit__(None, None, None)
    assert http_client.closed


# ---------------------------------------------------------------------------
# post(), put(), patch(), delete() method delegations (lines 141, 157, 172, 187)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_delegates_to_request():
    async with AutomoxClient(org_id=42) as client:
        (http_client,) = StubAsyncClient.instances
        http_client.responses = [StubResponse(json_data={"created": True})]
        result = await client.post("/items", json_data={"name": "x"})

    assert result == {"created": True}
    call = http_client.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/items"
    assert call["json"] == {"name": "x"}


@pytest.mark.asyncio
async def test_put_delegates_to_request():
    async with AutomoxClient(org_id=42) as client:
        (http_client,) = StubAsyncClient.instances
        http_client.responses = [StubResponse(json_data={"updated": True})]
        result = await client.put("/items/1", json_data={"name": "y"})

    assert result == {"updated": True}
    call = http_client.calls[0]
    assert call["method"] == "PUT"
    assert call["path"] == "/items/1"


@pytest.mark.asyncio
async def test_patch_delegates_to_request():
    async with AutomoxClient(org_id=42) as client:
        (http_client,) = StubAsyncClient.instances
        http_client.responses = [StubResponse(json_data={"patched": True})]
        result = await client.patch("/items/1", json_data={"active": False})

    assert result == {"patched": True}
    call = http_client.calls[0]
    assert call["method"] == "PATCH"
    assert call["path"] == "/items/1"


@pytest.mark.asyncio
async def test_delete_delegates_to_request():
    """delete() with a 204 No Content response returns an empty dict."""
    async with AutomoxClient(org_id=42) as client:
        (http_client,) = StubAsyncClient.instances
        # 204 has no body — the client should return {}
        http_client.responses = [StubResponse(status_code=204)]
        result = await client.delete("/items/1")

    assert result == {}
    call = http_client.calls[0]
    assert call["method"] == "DELETE"
    assert call["path"] == "/items/1"


# ---------------------------------------------------------------------------
# Network error handling (lines 217-218)
# ---------------------------------------------------------------------------


class RaisingAsyncClient(StubAsyncClient):
    """Variant that raises httpx.RequestError on every request."""

    async def request(self, method, path, **kwargs):
        import httpx

        raise httpx.ConnectError("connection refused")


@pytest.mark.asyncio
async def test_network_error_raises_automox_api_error(monkeypatch):
    monkeypatch.setattr("automox_mcp.client.httpx.AsyncClient", RaisingAsyncClient)
    async with AutomoxClient(org_id=42) as client:
        with pytest.raises(AutomoxAPIError, match="network error"):
            await client.get("/anything")


# ---------------------------------------------------------------------------
# Invalid JSON on a non-error response (line 231)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_json_on_200_raises_api_error():
    async with AutomoxClient(org_id=42) as client:
        (http_client,) = StubAsyncClient.instances
        http_client.responses = [
            StubResponse(status_code=200, text="<html>oops</html>", json_error=True),
        ]
        with pytest.raises(AutomoxAPIError, match="invalid JSON"):
            await client.get("/bad-content")


# ---------------------------------------------------------------------------
# _build_error with non-JSON error body (lines 247-249)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_error_non_json_body_uses_text():
    """When the error response body is not valid JSON, _extract_error_payload falls back to text."""
    async with AutomoxClient(org_id=42) as client:
        (http_client,) = StubAsyncClient.instances
        http_client.responses = [
            StubResponse(status_code=500, text="Internal Server Error", json_error=True),
        ]
        with pytest.raises(AutomoxAPIError) as exc_info:
            await client.get("/broken")

    err = exc_info.value
    assert err.status_code == 500
    # The plain-text body should be surfaced in the payload
    assert err.payload.get("message") == "Internal Server Error"

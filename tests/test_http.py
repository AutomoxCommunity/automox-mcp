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

    def __init__(self, *, base_url: str, headers: dict[str, str], timeout: Any) -> None:
        self.base_url = base_url
        self.headers = headers
        self.timeout = timeout
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
async def test_get_success_uses_console_client():
    async with AutomoxClient(org_id=42) as client:
        console_client, policy_client = StubAsyncClient.instances
        console_client.responses = [StubResponse(json_data={"ok": True})]
        payload = await client.get("/foo")

    assert payload == {"ok": True}
    assert console_client.calls[0]["path"] == "/foo"
    assert console_client.headers["Authorization"] == "Bearer test-key"
    assert policy_client.calls == []


@pytest.mark.asyncio
async def test_get_uses_policyreport_when_requested():
    async with AutomoxClient(org_id=42) as client:
        console_client, policy_client = StubAsyncClient.instances
        policy_client.responses = [StubResponse(json_data={"ok": True})]
        payload = await client.get("/foo", api="policyreport")

    assert payload == {"ok": True}
    assert policy_client.calls[0]["path"] == "/foo"
    assert policy_client.headers["Authorization"] == "Bearer test-key"
    assert console_client.calls == []


@pytest.mark.asyncio
async def test_get_raises_rate_limit():
    async with AutomoxClient(org_id=42) as client:
        console_client, _ = StubAsyncClient.instances
        console_client.responses = [
            StubResponse(status_code=429, json_data={"message": "slow down"})
        ]
        with pytest.raises(AutomoxRateLimitError):
            await client.get("/retry")


@pytest.mark.asyncio
async def test_get_raises_api_error_with_payload():
    async with AutomoxClient(org_id=42) as client:
        console_client, _ = StubAsyncClient.instances
        console_client.responses = [
            StubResponse(status_code=401, json_data={"message": "bad auth", "code": "unauthorized"})
        ]
        with pytest.raises(AutomoxAPIError) as exc:
            await client.get("/auth")

    assert exc.value.status_code == 401
    assert exc.value.payload["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_invalid_json_falls_back_to_policyreport():
    async with AutomoxClient(org_id=42) as client:
        console_client, policy_client = StubAsyncClient.instances
        console_client.responses = [
            StubResponse(status_code=200, text="not json", json_error=True),
        ]
        policy_client.responses = [StubResponse(json_data={"ok": True})]

        payload = await client.get("/foo")

    assert payload == {"ok": True}
    assert console_client.calls[0]["path"] == "/foo"
    assert policy_client.calls[0]["path"] == "/foo"

import pytest

from automox_mcp import create_server
from automox_mcp.client import AutomoxClient


class NullAsyncClient:
    instances = 0

    def __init__(self, *, base_url: str, headers: dict[str, str], timeout):
        NullAsyncClient.instances += 1
        self.base_url = base_url
        self.headers = headers
        self.timeout = timeout

    async def request(self, *args, **kwargs):  # pragma: no cover - not used in these tests
        raise NotImplementedError

    async def aclose(self) -> None:  # pragma: no cover - nothing to close in stub
        return None


@pytest.fixture(autouse=True)
def patch_async_client(monkeypatch):
    NullAsyncClient.instances = 0
    monkeypatch.setattr("automox_mcp.client.httpx.AsyncClient", NullAsyncClient)
    yield
    NullAsyncClient.instances = 0


def test_client_reads_environment_defaults(monkeypatch):
    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "17")

    client = AutomoxClient()

    assert client.api_key == "env-key"
    assert client.account_uuid == "account-uuid"
    assert client.org_id == 17
    assert NullAsyncClient.instances == 2  # console + policyreport clients are created


def test_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("AUTOMOX_API_KEY", raising=False)
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")

    with pytest.raises(ValueError, match="AUTOMOX_API_KEY environment variable is required"):
        AutomoxClient()


def test_client_requires_account_uuid(monkeypatch):
    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.delenv("AUTOMOX_ACCOUNT_UUID", raising=False)

    with pytest.raises(ValueError, match="AUTOMOX_ACCOUNT_UUID environment variable is required"):
        AutomoxClient()


@pytest.mark.parametrize(
    "missing_env",
    ["AUTOMOX_API_KEY", "AUTOMOX_ACCOUNT_UUID", "AUTOMOX_ORG_ID"],
)
def test_create_server_requires_environment(monkeypatch, missing_env):
    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "17")
    monkeypatch.setenv("AUTOMOX_MCP_SKIP_DOTENV", "1")
    monkeypatch.delenv(missing_env, raising=False)

    with pytest.raises(RuntimeError) as exc:
        create_server()

    assert missing_env in str(exc.value)

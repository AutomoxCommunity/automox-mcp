import pytest

from automox_mcp import create_server
from automox_mcp.client import AutomoxClient


class NullAsyncClient:
    instances = 0

    def __init__(self, *, base_url: str, headers: dict[str, str], timeout, auth=None):
        NullAsyncClient.instances += 1
        self.base_url = base_url
        self.headers = headers
        self.timeout = timeout
        self.auth = auth

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

    assert client._api_key == "env-key"
    assert client.account_uuid == "account-uuid"
    assert client.org_id == 17
    assert NullAsyncClient.instances == 1  # single _http client is created


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
    ["AUTOMOX_API_KEY", "AUTOMOX_ACCOUNT_UUID"],
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


def test_create_server_rejects_non_integer_org_id(monkeypatch):
    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "not-a-number")
    monkeypatch.setenv("AUTOMOX_MCP_SKIP_DOTENV", "1")

    with pytest.raises(RuntimeError, match="AUTOMOX_ORG_ID must be a positive integer"):
        create_server()


def test_create_server_rejects_negative_org_id(monkeypatch):
    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "-5")
    monkeypatch.setenv("AUTOMOX_MCP_SKIP_DOTENV", "1")

    with pytest.raises(RuntimeError, match="AUTOMOX_ORG_ID must be a positive integer"):
        create_server()


def test_create_server_calls_dotenv_when_not_skipped(monkeypatch):
    import automox_mcp.server as server_mod

    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "17")
    monkeypatch.delenv("AUTOMOX_MCP_SKIP_DOTENV", raising=False)

    called: list[bool] = []

    def fake_load_dotenv():
        called.append(True)
        return True

    monkeypatch.setattr(server_mod, "_load_dotenv_fn", fake_load_dotenv)

    create_server()

    assert called, "expected _load_dotenv_fn to be called"


def test_validate_env_zero_org_id_rejected(monkeypatch):
    from automox_mcp.server import _validate_env

    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "0")

    with pytest.raises(RuntimeError, match="AUTOMOX_ORG_ID must be a positive integer"):
        _validate_env()


# ---------------------------------------------------------------------------
# automox_mcp.__init__ — env helpers, _parse_args, and main()
# ---------------------------------------------------------------------------


def test_env_str_returns_none_when_unset(monkeypatch):
    from automox_mcp import _env_str

    monkeypatch.delenv("AUTOMOX_TEST_VAR_XYZ", raising=False)
    assert _env_str("AUTOMOX_TEST_VAR_XYZ") is None


def test_env_str_strips_and_returns_none_for_blank(monkeypatch):
    from automox_mcp import _env_str

    monkeypatch.setenv("AUTOMOX_TEST_VAR_XYZ", "   ")
    assert _env_str("AUTOMOX_TEST_VAR_XYZ") is None


def test_env_str_returns_stripped_value(monkeypatch):
    from automox_mcp import _env_str

    monkeypatch.setenv("AUTOMOX_TEST_VAR_XYZ", "  hello  ")
    assert _env_str("AUTOMOX_TEST_VAR_XYZ") == "hello"


def test_env_flag_returns_default_when_unset(monkeypatch):
    from automox_mcp import _env_flag

    monkeypatch.delenv("AUTOMOX_TEST_FLAG_XYZ", raising=False)
    assert _env_flag("AUTOMOX_TEST_FLAG_XYZ", default=True) is True
    assert _env_flag("AUTOMOX_TEST_FLAG_XYZ", default=False) is False


def test_env_flag_parses_true_values(monkeypatch):
    from automox_mcp import _env_flag

    for val in ("1", "true", "yes", "on", "TRUE", "YES"):
        monkeypatch.setenv("AUTOMOX_TEST_FLAG_XYZ", val)
        assert _env_flag("AUTOMOX_TEST_FLAG_XYZ") is True


def test_env_flag_parses_false_values(monkeypatch):
    from automox_mcp import _env_flag

    for val in ("0", "false", "no", "off"):
        monkeypatch.setenv("AUTOMOX_TEST_FLAG_XYZ", val)
        assert _env_flag("AUTOMOX_TEST_FLAG_XYZ") is False


def test_parse_args_defaults(monkeypatch):
    from automox_mcp import _parse_args

    monkeypatch.delenv("AUTOMOX_MCP_SHOW_BANNER", raising=False)
    args = _parse_args([])
    assert args.transport is None
    assert args.host is None
    assert args.port is None
    assert args.path is None
    assert args.show_banner is False


def test_parse_args_with_transport(monkeypatch):
    from automox_mcp import _parse_args

    monkeypatch.delenv("AUTOMOX_MCP_SHOW_BANNER", raising=False)
    args = _parse_args(["--transport", "http", "--host", "0.0.0.0", "--port", "9000"])
    assert args.transport == "http"
    assert args.host == "0.0.0.0"
    assert args.port == 9000


def test_parse_args_show_banner_flag(monkeypatch):
    from automox_mcp import _parse_args

    monkeypatch.delenv("AUTOMOX_MCP_SHOW_BANNER", raising=False)
    args = _parse_args(["--show-banner"])
    assert args.show_banner is True

    args2 = _parse_args(["--no-banner"])
    assert args2.show_banner is False


def test_main_raises_on_unsupported_transport(monkeypatch):
    from automox_mcp import main

    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "17")
    monkeypatch.setenv("AUTOMOX_MCP_SKIP_DOTENV", "1")
    monkeypatch.setenv("AUTOMOX_MCP_TRANSPORT", "grpc")

    with pytest.raises(SystemExit):
        main([])


def test_main_stdio_transport_calls_run(monkeypatch):
    import automox_mcp as init_mod

    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "17")
    monkeypatch.setenv("AUTOMOX_MCP_SKIP_DOTENV", "1")
    monkeypatch.delenv("AUTOMOX_MCP_TRANSPORT", raising=False)

    run_calls: list[dict] = []

    class FakeServer:
        def run(self, *, transport, show_banner, **kwargs):
            run_calls.append({"transport": transport, "show_banner": show_banner, **kwargs})

    monkeypatch.setattr(init_mod.mcp, "_instance", FakeServer())

    init_mod.main([])

    assert len(run_calls) == 1
    assert run_calls[0]["transport"] == "stdio"


def test_main_http_transport_sets_defaults(monkeypatch):
    import automox_mcp as init_mod

    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "17")
    monkeypatch.setenv("AUTOMOX_MCP_SKIP_DOTENV", "1")
    monkeypatch.delenv("AUTOMOX_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("AUTOMOX_MCP_HOST", raising=False)
    monkeypatch.delenv("AUTOMOX_MCP_PORT", raising=False)
    monkeypatch.delenv("AUTOMOX_MCP_PATH", raising=False)

    run_calls: list[dict] = []

    class FakeServer:
        def run(self, *, transport, show_banner, **kwargs):
            run_calls.append({"transport": transport, **kwargs})

    monkeypatch.setattr(init_mod.mcp, "_instance", FakeServer())

    init_mod.main(["--transport", "http"])

    assert run_calls[0]["host"] == "127.0.0.1"
    assert run_calls[0]["port"] == 8000


def test_main_http_transport_with_explicit_host_port(monkeypatch):
    import automox_mcp as init_mod

    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "17")
    monkeypatch.setenv("AUTOMOX_MCP_SKIP_DOTENV", "1")
    monkeypatch.delenv("AUTOMOX_MCP_TRANSPORT", raising=False)

    run_calls: list[dict] = []

    class FakeServer:
        def run(self, *, transport, show_banner, **kwargs):
            run_calls.append({"transport": transport, **kwargs})

    monkeypatch.setattr(init_mod.mcp, "_instance", FakeServer())

    init_mod.main(["--transport", "http", "--host", "127.0.0.1", "--port", "7777"])

    assert run_calls[0]["host"] == "127.0.0.1"
    assert run_calls[0]["port"] == 7777


def test_main_http_non_loopback_host_rejected_without_flag(monkeypatch):
    import automox_mcp as init_mod

    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "17")
    monkeypatch.setenv("AUTOMOX_MCP_SKIP_DOTENV", "1")
    monkeypatch.delenv("AUTOMOX_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("AUTOMOX_MCP_ALLOW_REMOTE_BIND", raising=False)

    class FakeServer:
        def run(self, *, transport, show_banner, **kwargs):
            pass

    monkeypatch.setattr(init_mod.mcp, "_instance", FakeServer())

    with pytest.raises(SystemExit, match="allow-remote-bind"):
        init_mod.main(["--transport", "http", "--host", "0.0.0.0", "--port", "8080"])


def test_main_http_non_loopback_host_allowed_with_flag(monkeypatch, caplog):
    import logging

    import automox_mcp as init_mod

    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "17")
    monkeypatch.setenv("AUTOMOX_MCP_SKIP_DOTENV", "1")
    monkeypatch.delenv("AUTOMOX_MCP_TRANSPORT", raising=False)

    class FakeServer:
        def run(self, *, transport, show_banner, **kwargs):
            pass

    monkeypatch.setattr(init_mod.mcp, "_instance", FakeServer())

    with caplog.at_level(logging.WARNING, logger="automox_mcp"):
        init_mod.main(
            [
                "--transport",
                "http",
                "--host",
                "0.0.0.0",
                "--port",
                "8080",
                "--allow-remote-bind",
            ]
        )

    assert any("non-loopback" in r.message for r in caplog.records)


def test_main_http_port_from_env(monkeypatch):
    import automox_mcp as init_mod

    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "17")
    monkeypatch.setenv("AUTOMOX_MCP_SKIP_DOTENV", "1")
    monkeypatch.setenv("AUTOMOX_MCP_PORT", "9999")
    monkeypatch.delenv("AUTOMOX_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("AUTOMOX_MCP_HOST", raising=False)

    run_calls: list[dict] = []

    class FakeServer:
        def run(self, *, transport, show_banner, **kwargs):
            run_calls.append(kwargs)

    monkeypatch.setattr(init_mod.mcp, "_instance", FakeServer())
    init_mod.main(["--transport", "http"])

    assert run_calls[0]["port"] == 9999


def test_main_http_path_kwarg(monkeypatch):
    import automox_mcp as init_mod

    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "17")
    monkeypatch.setenv("AUTOMOX_MCP_SKIP_DOTENV", "1")
    monkeypatch.delenv("AUTOMOX_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("AUTOMOX_MCP_HOST", raising=False)
    monkeypatch.delenv("AUTOMOX_MCP_PORT", raising=False)

    run_calls: list[dict] = []

    class FakeServer:
        def run(self, *, transport, show_banner, **kwargs):
            run_calls.append(kwargs)

    monkeypatch.setattr(init_mod.mcp, "_instance", FakeServer())
    init_mod.main(["--transport", "sse", "--path", "/custom"])

    assert run_calls[0]["path"] == "/custom"


def test_main_lazy_server_creates_instance(monkeypatch):
    """_LazyServer.__getattr__ triggers create_server on first access."""
    import automox_mcp as init_mod

    monkeypatch.setenv("AUTOMOX_API_KEY", "env-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "account-uuid")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "17")
    monkeypatch.setenv("AUTOMOX_MCP_SKIP_DOTENV", "1")

    lazy = init_mod._LazyServer()
    assert lazy._instance is None
    # Access an attribute to trigger creation
    name = lazy.name
    assert lazy._instance is not None
    assert name is not None

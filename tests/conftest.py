import copy
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _reset_shared_state():
    """Clear global rate limiter and idempotency cache between tests."""
    from automox_mcp.utils.tooling import _IDEMPOTENCY_CACHE, _RATE_LIMITER

    _RATE_LIMITER._timestamps.clear()
    _IDEMPOTENCY_CACHE.clear()
    yield
    _RATE_LIMITER._timestamps.clear()
    _IDEMPOTENCY_CACHE.clear()


# ---------------------------------------------------------------------------
# Shared StubServer for tool registration tests
# ---------------------------------------------------------------------------


class StubServer:
    """Lightweight FastMCP lookalike that captures registered tool functions.

    Used by tool-registration and tool-dispatch tests to avoid importing
    the full FastMCP server.
    """

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, name: str, description: str = "", **kwargs):
        def decorator(func):
            self.tools[name] = func
            return func

        return decorator


# ---------------------------------------------------------------------------
# Shared FakeClient for tool tests
# ---------------------------------------------------------------------------


class FakeClient:
    """Minimal client stub with configurable responses.

    Used by tool-dispatch and tool-registration tests where the full
    StubClient request/response infrastructure is not needed.
    """

    def __init__(
        self,
        *,
        org_id: int | None = 42,
        org_uuid: str | None = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        account_uuid: str = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    ) -> None:
        self.org_id = org_id
        self.org_uuid = org_uuid
        self.account_uuid = account_uuid
        self._get_response: Any = []
        self._post_response: Any = {}

    async def get(self, path: str, *, params: Any = None, headers: Any = None) -> Any:
        return self._get_response

    async def post(
        self, path: str, *, json_data: Any = None, params: Any = None, headers: Any = None
    ) -> Any:
        return self._post_response


# ---------------------------------------------------------------------------
# Shared StubClient for workflow tests
# ---------------------------------------------------------------------------


class StubClient:
    """Minimal Automox client stub that records calls and returns canned responses.

    Responses are keyed by request path.  Each path maps to a *list* of
    responses that are popped in order (FIFO).  When a path has no remaining
    responses an empty ``dict`` is returned (or ``None`` for DELETE).

    Set ``org_id``, ``org_uuid``, and ``account_uuid`` directly on the
    instance when the workflow under test needs them.
    """

    def __init__(
        self,
        *,
        get_responses: dict[str, list[Any]] | None = None,
        post_responses: dict[str, list[Any]] | None = None,
        put_responses: dict[str, list[Any]] | None = None,
        patch_responses: dict[str, list[Any]] | None = None,
        delete_responses: dict[str, list[Any]] | None = None,
    ) -> None:
        self._get = {k: list(v) for k, v in (get_responses or {}).items()}
        self._post = {k: list(v) for k, v in (post_responses or {}).items()}
        self._put = {k: list(v) for k, v in (put_responses or {}).items()}
        self._patch = {k: list(v) for k, v in (patch_responses or {}).items()}
        self._delete = {k: list(v) for k, v in (delete_responses or {}).items()}
        self.calls: list[tuple[str, str, Any]] = []
        # Sensible defaults; override in individual tests as needed.
        self.org_id: int | None = 42
        self.org_uuid: str | None = None
        self.account_uuid: str = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    _SENTINEL = object()

    def _pop(self, store: dict[str, list[Any]], path: str, default: Any = _SENTINEL) -> Any:
        """Match *path* against stored responses, supporting prefix matching."""
        responses = store.get(path)
        if responses:
            return copy.deepcopy(responses.pop(0))
        # Prefix match for paths with query strings
        for key, resps in store.items():
            if path.startswith(key) and resps:
                return copy.deepcopy(resps.pop(0))
        return {} if default is self._SENTINEL else default

    async def get(self, path: str, *, params: Any = None, headers: Any = None) -> Any:
        self.calls.append(("GET", path, params))
        return self._pop(self._get, path)

    async def post(
        self, path: str, *, json_data: Any = None, params: Any = None, headers: Any = None
    ) -> Any:
        self.calls.append(("POST", path, json_data))
        return self._pop(self._post, path)

    async def put(
        self, path: str, *, json_data: Any = None, params: Any = None, headers: Any = None
    ) -> Any:
        self.calls.append(("PUT", path, json_data))
        return self._pop(self._put, path)

    async def patch(
        self, path: str, *, json_data: Any = None, params: Any = None, headers: Any = None
    ) -> Any:
        self.calls.append(("PATCH", path, json_data))
        return self._pop(self._patch, path)

    async def delete(self, path: str, *, params: Any = None, headers: Any = None) -> Any:
        self.calls.append(("DELETE", path, params))
        return self._pop(self._delete, path, default=None)

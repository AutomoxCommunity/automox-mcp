"""Utility helpers shared by MCP tools."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, cast

from pydantic import BaseModel

from ..client import AutomoxAPIError
from ..middleware import get_correlation_id
from ..schemas import PaginationMetadata, ToolResponse
from .sanitize import is_sanitization_enabled, sanitize_dict, sanitize_for_llm

logger = logging.getLogger(__name__)

_VALID_MODULES: frozenset[str] = frozenset(
    {
        "audit",
        "audit_v2",
        "devices",
        "device_search",
        "policies",
        "policy_history",
        "users",
        "groups",
        "events",
        "reports",
        "packages",
        "webhooks",
        "worklets",
        "data_extracts",
        "vuln_sync",
        "compound",
        "policy_windows",
    }
)

# S-003: "key" and "auth" were intentionally removed to prevent over-redaction
# of legitimate Automox fields like "registry_key" and "author".  This is safe
# because _redact_sensitive_fields is only applied to error payloads already
# filtered through _ALLOWED_ERROR_KEYS (code, detail, message, title, error),
# so auth-related field names never appear in the redaction input.
SENSITIVE_KEYWORDS: tuple[str, ...] = (
    "token",
    "secret",
    "api_key",
    "api-key",
    "apikey",
    "password",
    "credential",
    "bearer",
    "passwd",
)


def is_read_only() -> bool:
    """Return True when the server is running in read-only mode."""
    value = os.environ.get("AUTOMOX_MCP_READ_ONLY", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_tool_prefix() -> str:
    """Return the configured tool name prefix, or empty string if none."""
    return os.environ.get("AUTOMOX_MCP_TOOL_PREFIX", "").strip()


def get_enabled_modules() -> set[str] | None:
    """Return the set of enabled module names, or None if all are enabled.

    Controlled by ``AUTOMOX_MCP_MODULES`` (comma-separated).  Valid names:
    audit, audit_v2, devices, device_search, policies, policy_history,
    users, groups, events, reports, packages, webhooks, worklets,
    data_extracts, vuln_sync, compound.
    """
    raw = os.environ.get("AUTOMOX_MCP_MODULES", "").strip()
    if not raw:
        return None
    modules = {m.strip().lower() for m in raw.split(",") if m.strip()}
    unknown = modules - _VALID_MODULES
    if unknown:
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "AUTOMOX_MCP_MODULES contains unknown module names: %s. Valid names: %s",
            ", ".join(sorted(unknown)),
            ", ".join(sorted(_VALID_MODULES)),
        )
    return modules


class RateLimitError(RuntimeError):
    """Raised when a tool exceeds the configured rate limit."""


_SENTINEL_IN_FLIGHT = "__in_flight__"


class IdempotencyCache:
    """In-memory TTL cache for idempotent write operations.

    V-156: Uses a get-or-reserve pattern to prevent duplicate writes from
    concurrent requests with the same ``request_id``.  ``reserve()`` atomically
    checks for an existing entry *and* inserts an in-flight placeholder when
    none exists, closing the TOCTOU gap between check and store.
    """

    _MAX_ENTRIES = 1000

    def __init__(self, *, ttl_seconds: float = 300.0) -> None:
        self._ttl = ttl_seconds
        self._cache: dict[tuple[str, str], tuple[dict[str, Any] | str, float]] = {}
        self._lock = asyncio.Lock()

    async def reserve(
        self, request_id: str, tool_name: str
    ) -> tuple[bool, dict[str, Any] | None]:
        """Atomically check-and-reserve a request_id slot.

        Returns ``(True, cached_response)`` if a completed response exists,
        ``(True, None)`` if another caller already reserved the slot (duplicate
        in-flight), or ``(False, None)`` when a fresh reservation was created.
        """
        async with self._lock:
            self._evict_expired()
            key = (request_id, tool_name)
            entry = self._cache.get(key)
            if entry is not None:
                value, expiry = entry
                if time.monotonic() > expiry:
                    del self._cache[key]
                elif isinstance(value, dict):
                    return True, value  # Completed — return cached
                else:
                    return True, None  # In-flight — duplicate request
            # Reserve the slot with a sentinel
            self._cache[key] = (_SENTINEL_IN_FLIGHT, time.monotonic() + self._ttl)
            return False, None

    async def get(self, request_id: str, tool_name: str) -> dict[str, Any] | None:
        async with self._lock:
            self._evict_expired()
            key = (request_id, tool_name)
            entry = self._cache.get(key)
            if entry is None:
                return None
            value, expiry = entry
            if time.monotonic() > expiry:
                del self._cache[key]
                return None
            if isinstance(value, dict):
                return value
            return None  # In-flight sentinel — not yet complete

    async def put(self, request_id: str, tool_name: str, response: dict[str, Any]) -> None:
        async with self._lock:
            self._evict_expired()
            key = (request_id, tool_name)
            self._cache[key] = (response, time.monotonic() + self._ttl)

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._cache.items() if now > exp]
        for k in expired:
            del self._cache[k]
        # Hard cap to prevent unbounded growth
        if len(self._cache) >= self._MAX_ENTRIES:
            oldest = min(self._cache, key=lambda k: self._cache[k][1])
            del self._cache[oldest]

    def clear(self) -> None:
        self._cache.clear()


_IDEMPOTENCY_CACHE = IdempotencyCache()


async def check_idempotency(request_id: str | None, tool_name: str) -> dict[str, Any] | None:
    """Atomically check and reserve a request_id, returning a cached response if available.

    Returns the cached response dict when a previous call already completed,
    or ``None`` when the caller should proceed with the operation.  The slot
    is reserved under the hood so that concurrent duplicates see the in-flight
    sentinel and return a generic "duplicate" response instead of executing
    the operation a second time.
    """
    if not request_id:
        return None
    already_exists, cached = await _IDEMPOTENCY_CACHE.reserve(request_id, tool_name)
    if already_exists:
        if cached is not None:
            return cached
        # Another request is in flight — return a minimal duplicate marker.
        return {"data": {"duplicate": True, "request_id": request_id}, "metadata": {}}
    return None


async def store_idempotency(
    request_id: str | None, tool_name: str, response: dict[str, Any]
) -> None:
    """Cache a response for idempotent replay."""
    if not request_id:
        return
    await _IDEMPOTENCY_CACHE.put(request_id, tool_name, response)


class RateLimiter:
    """Simple sliding window rate limiter to throttle outbound API usage."""

    def __init__(self, *, name: str, max_calls: int, period_seconds: float) -> None:
        if max_calls <= 0:
            raise ValueError("max_calls must be greater than zero")
        if period_seconds <= 0:
            raise ValueError("period_seconds must be greater than zero")
        self._name = name
        self._max_calls = max_calls
        self._period = period_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            window_start = now - self._period
            while self._timestamps and self._timestamps[0] <= window_start:
                self._timestamps.popleft()
            if len(self._timestamps) >= self._max_calls:
                raise RateLimitError(
                    f"{self._name} rate limit exceeded "
                    f"({self._max_calls} calls per {int(self._period)}s)."
                )
            self._timestamps.append(now)


_RATE_LIMITER = RateLimiter(name="Automox API", max_calls=30, period_seconds=60.0)


async def enforce_rate_limit() -> None:
    """Ensure the current invocation does not exceed the API rate limit."""
    await _RATE_LIMITER.acquire()


_ALLOWED_ERROR_KEYS = {"code", "detail", "message", "title", "error"}


def _has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, Sequence)) and not isinstance(value, (str, bytes, bytearray)):
        return bool(value)
    return True


def _sanitize_errors(value: Any) -> Any:
    if isinstance(value, Mapping):
        cleaned = {
            key: item
            for key, item in value.items()
            if key in _ALLOWED_ERROR_KEYS and _has_content(item)
        }
        return cleaned or None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        cleaned_list = []
        for item in value:
            if isinstance(item, Mapping):
                cleaned_item = {
                    key: val
                    for key, val in item.items()
                    if key in _ALLOWED_ERROR_KEYS and _has_content(val)
                }
                if cleaned_item:
                    cleaned_list.append(cleaned_item)
            elif _has_content(item):
                cleaned_list.append(item)
        return cleaned_list or None
    if _has_content(value):
        return value
    return None


def _redact_sensitive_fields(payload: Any, *, _depth: int = 0) -> Any:
    _MAX_REDACTION_DEPTH = 20
    if _depth > _MAX_REDACTION_DEPTH:
        return "***redacted: max depth***"
    if isinstance(payload, Mapping):
        redacted: dict[Any, Any] = {}
        for key, value in payload.items():
            lower_key = str(key).lower()
            if any(sensitive in lower_key for sensitive in SENSITIVE_KEYWORDS):
                redacted[key] = "***redacted***"
            else:
                redacted[key] = _redact_sensitive_fields(value, _depth=_depth + 1)
        return redacted
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [_redact_sensitive_fields(item, _depth=_depth + 1) for item in payload]
    return payload


def _sanitize_error_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = {
        key: value
        for key, value in payload.items()
        if key in _ALLOWED_ERROR_KEYS and _has_content(value)
    }
    errors = payload.get("errors")
    sanitized_errors = _sanitize_errors(errors)
    if sanitized_errors is not None:
        sanitized["errors"] = sanitized_errors
    return sanitized


def format_error(exc: AutomoxAPIError) -> str:
    """Format an AutomoxAPIError for display to the user.

    The formatted string is sanitized against prompt injection before being
    returned, because callers raise it as a ``ToolError`` that goes directly
    to the LLM without passing through ``as_tool_response`` / ``sanitize_dict``.
    """
    payload = exc.payload or {}
    safe_payload = _sanitize_error_payload(payload)
    if not safe_payload and payload:
        safe_payload = _redact_sensitive_fields(payload)
    try:
        payload_block = json.dumps(safe_payload, indent=2, sort_keys=True) if safe_payload else None
    except TypeError:
        payload_block = repr(safe_payload)
    payload_text = payload_block or "No additional details"
    message = f"{str(exc)} (status={exc.status_code})\n\nAPI Response:\n{payload_text}"
    if is_sanitization_enabled():
        message = sanitize_for_llm(message, field_name="message")
    return message


def format_validation_error(exc: Exception) -> str:
    """Sanitize a ValidationError/ValueError message before it reaches the LLM.

    Pydantic ``ValidationError`` messages can echo back raw input values.
    This prevents attacker-controlled data from reaching the LLM via
    deliberately malformed tool parameters (V-124).
    """
    message = str(exc)
    if is_sanitization_enabled():
        message = sanitize_for_llm(message, field_name="message")
    # Truncate to prevent oversized validation errors from consuming token budget
    if len(message) > 500:
        message = message[:500] + "… (truncated)"
    return message


_CHARS_PER_TOKEN = 4
try:
    _raw_budget = int(os.environ.get("AUTOMOX_MCP_TOKEN_BUDGET", "4000"))
    _DEFAULT_TOKEN_BUDGET = _raw_budget if _raw_budget > 0 else 4000
except (ValueError, TypeError):
    _DEFAULT_TOKEN_BUDGET = 4000


def _estimate_tokens(response_dict: dict[str, Any]) -> int:
    """Rough token estimate: JSON character count / 4."""
    try:
        return len(json.dumps(response_dict, default=str)) // _CHARS_PER_TOKEN
    except (TypeError, ValueError, OverflowError):
        # Fallback: estimate from repr length to avoid bypassing budget
        try:
            return len(repr(response_dict)) // _CHARS_PER_TOKEN
        except Exception:
            return _DEFAULT_TOKEN_BUDGET  # assume at-budget to trigger truncation check


def _apply_token_budget(
    response_dict: dict[str, Any],
    *,
    budget: int | None = None,
) -> dict[str, Any]:
    """Add a token warning and optionally truncate list data.

    Works on a deep copy to avoid mutating cached data.
    """
    effective_budget = budget if budget is not None else _DEFAULT_TOKEN_BUDGET
    estimated = _estimate_tokens(response_dict)
    if estimated <= effective_budget:
        return response_dict

    # Deep copy to avoid mutating idempotency cache entries
    response_dict = copy.deepcopy(response_dict)

    meta = response_dict.setdefault("metadata", {})
    meta["estimated_tokens"] = estimated
    meta["token_warning"] = (
        f"Response is ~{estimated} tokens (budget: {effective_budget}). "
        "Consider using pagination or filters to reduce size."
    )

    # Truncate list data if the data payload contains a list
    data = response_dict.get("data")
    if isinstance(data, list) and len(data) > 1:
        total = len(data)
        response_dict["data"] = data[: max(total // 2, 1)]
        meta["truncated"] = True
        meta["total_available"] = total
        meta["returned_count"] = len(response_dict["data"])
    elif isinstance(data, Mapping):
        # Truncate ALL oversized lists in the mapping, not just the first
        for _key, value in data.items():
            if isinstance(value, list) and len(value) > 1:
                total = len(value)
                data[_key] = value[: max(total // 2, 1)]
                meta["truncated"] = True
                meta.setdefault("total_available", 0)
                meta["total_available"] += total

    return response_dict


def as_tool_response(result: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a workflow result to a standardized tool response."""
    metadata_input = result.get("metadata") or {}
    if not isinstance(metadata_input, Mapping):
        metadata_input = {}
    metadata_dict = dict(metadata_input)
    correlation_id = get_correlation_id()
    if correlation_id:
        metadata_dict["correlation_id"] = correlation_id
    data = result.get("data")
    metadata = PaginationMetadata(**metadata_dict)
    response = ToolResponse(data=data, metadata=metadata)
    response_dict = cast(dict[str, Any], response.model_dump())
    if is_sanitization_enabled():
        response_dict = sanitize_dict(response_dict)
    return _apply_token_budget(response_dict)


def format_as_markdown_table(data: list[dict[str, Any]], *, max_col_width: int = 40) -> str:
    """Convert a list of flat dicts into a Markdown table string."""
    if not data:
        return "_No data_"

    # Collect all keys preserving insertion order
    columns: list[str] = []
    seen: set[str] = set()
    for row in data:
        for key in row:
            if key not in seen:
                columns.append(key)
                seen.add(key)

    def _cell(value: Any) -> str:
        text = str(value) if value is not None else ""
        if len(text) > max_col_width:
            text = text[: max_col_width - 3] + "..."
        return text.replace("|", "\\|")

    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"

    rows = []
    for row in data:
        cells = [_cell(row.get(col)) for col in columns]
        rows.append("| " + " | ".join(cells) + " |")

    return "\n".join([header, separator, *rows])


def maybe_format_markdown(result: dict[str, Any], output_format: str | None) -> dict[str, Any]:
    """If *output_format* is ``"markdown"``, convert the first list in *data* to a table.

    Returns the original *result* unchanged when the format is not markdown.
    """
    if output_format != "markdown":
        return result
    data = result.get("data", {})
    if isinstance(data, Mapping):
        for _key, value in data.items():
            if isinstance(value, list) and value:
                return {"data": format_as_markdown_table(value), "metadata": {"format": "markdown"}}
    # Cannot convert to markdown table — return original result unchanged
    return result


async def call_tool_workflow(
    client: Any,
    func: Callable[..., Awaitable[dict[str, Any]]],
    raw_params: dict[str, Any],
    *,
    params_model: type[BaseModel] | None = None,
    inject_org_id: bool = False,
    org_uuid_field: str | None = None,
    allow_account_uuid: bool = False,
    dump_mode: str = "python",
) -> dict[str, Any]:
    """Shared tool-call envelope: rate-limit, validate, invoke, format response.

    Parameters
    ----------
    client:
        The ``AutomoxClient`` instance.
    func:
        Async workflow function to call with ``(client, **payload)``.
    raw_params:
        Raw parameter dict from the tool caller.
    params_model:
        Optional Pydantic model for validation. When ``None``, *raw_params*
        are passed through with ``None`` values stripped.
    inject_org_id:
        When ``True`` and the model lacks an ``OrgIdContextMixin``/
        ``OrgIdRequiredMixin``, inject ``client.org_id`` into the payload.
    org_uuid_field:
        If set, resolve the org UUID (via ``resolve_org_uuid``) and inject it
        into params under this key before validation.
    allow_account_uuid:
        Passed through to ``resolve_org_uuid`` when *org_uuid_field* is set.
    dump_mode:
        Pydantic ``model_dump`` mode (``"python"`` or ``"json"``).
    """
    from fastmcp.exceptions import ToolError
    from pydantic import ValidationError

    from ..schemas import OrgIdContextMixin, OrgIdRequiredMixin

    try:
        await enforce_rate_limit()
        client_org_id = getattr(client, "org_id", None)
        params = dict(raw_params)

        # --- org UUID resolution (policy windows, webhooks, policy history) ---
        if org_uuid_field is not None:
            from .organization import resolve_org_uuid

            raw_org_id = params.get("org_id")
            resolved_uuid = await resolve_org_uuid(
                client,
                explicit_uuid=params.get(org_uuid_field),
                org_id=raw_org_id if raw_org_id is not None else client_org_id,
                allow_account_uuid=allow_account_uuid,
            )
            params[org_uuid_field] = resolved_uuid

        # --- parameter validation & org_id injection ---
        if params_model is not None:
            if issubclass(params_model, (OrgIdContextMixin, OrgIdRequiredMixin)):
                params.setdefault("org_id", client_org_id)
                if params.get("org_id") is None:
                    raise ToolError(
                        "org_id required - set AUTOMOX_ORG_ID or pass org_id explicitly."
                    )
            model = params_model(**params)
            payload = model.model_dump(mode=dump_mode, exclude_none=True)
            if isinstance(model, (OrgIdContextMixin, OrgIdRequiredMixin)):
                payload["org_id"] = model.org_id
            elif inject_org_id:
                if client_org_id is None:
                    raise ToolError(
                        "org_id required - set AUTOMOX_ORG_ID or pass org_id explicitly."
                    )
                payload["org_id"] = client_org_id
        else:
            payload = {k: v for k, v in params.items() if v is not None}

        result: dict[str, Any] = await func(client, **payload)
    except (ValidationError, ValueError) as exc:
        raise ToolError(format_validation_error(exc)) from exc
    except RateLimitError as exc:
        raise ToolError(str(exc)) from exc
    except AutomoxAPIError as exc:
        raise ToolError(format_error(exc)) from exc
    except ToolError:
        raise
    except Exception as exc:
        logger.exception("Unexpected error in tool call")
        raise ToolError("An internal error occurred. Check server logs for details.") from exc
    return as_tool_response(result)


__all__ = [
    "RateLimitError",
    "RateLimiter",
    "SENSITIVE_KEYWORDS",
    "as_tool_response",
    "call_tool_workflow",
    "check_idempotency",
    "enforce_rate_limit",
    "format_as_markdown_table",
    "format_error",
    "get_enabled_modules",
    "get_tool_prefix",
    "is_read_only",
    "maybe_format_markdown",
    "store_idempotency",
]

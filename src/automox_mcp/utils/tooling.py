"""Utility helpers shared by MCP tools."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any, cast

from ..client import AutomoxAPIError
from ..middleware import get_correlation_id
from ..schemas import PaginationMetadata, ToolResponse
from .sanitize import is_sanitization_enabled, sanitize_dict, sanitize_for_llm

_VALID_MODULES: frozenset[str] = frozenset({
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
})

SENSITIVE_KEYWORDS: tuple[str, ...] = (
    "token",
    "secret",
    "key",
    "password",
    "credential",
    "auth",
    "bearer",
    "passwd",
    "api-key",
    "apikey",
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


class IdempotencyCache:
    """In-memory TTL cache for idempotent write operations."""

    _MAX_ENTRIES = 1000

    def __init__(self, *, ttl_seconds: float = 300.0) -> None:
        self._ttl = ttl_seconds
        self._cache: dict[tuple[str, str], tuple[dict[str, Any], float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, request_id: str, tool_name: str) -> dict[str, Any] | None:
        async with self._lock:
            key = (request_id, tool_name)
            entry = self._cache.get(key)
            if entry is None:
                return None
            response, expiry = entry
            if time.monotonic() > expiry:
                del self._cache[key]
                return None
            return response

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
    """Return cached response for a duplicate request_id, or None."""
    if not request_id:
        return None
    return await _IDEMPOTENCY_CACHE.get(request_id, tool_name)


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


def _redact_sensitive_fields(payload: Any) -> Any:
    if isinstance(payload, Mapping):
        redacted: dict[Any, Any] = {}
        for key, value in payload.items():
            lower_key = str(key).lower()
            if any(sensitive in lower_key for sensitive in SENSITIVE_KEYWORDS):
                redacted[key] = "***redacted***"
            else:
                redacted[key] = _redact_sensitive_fields(value)
        return redacted
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [_redact_sensitive_fields(item) for item in payload]
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
    _DEFAULT_TOKEN_BUDGET = int(os.environ.get("AUTOMOX_MCP_TOKEN_BUDGET", "4000"))
except (ValueError, TypeError):
    _DEFAULT_TOKEN_BUDGET = 4000


def _estimate_tokens(response_dict: dict[str, Any]) -> int:
    """Rough token estimate: JSON character count / 4."""
    try:
        return len(json.dumps(response_dict)) // _CHARS_PER_TOKEN
    except (TypeError, ValueError):
        return 0


def _apply_token_budget(
    response_dict: dict[str, Any],
    *,
    budget: int | None = None,
) -> dict[str, Any]:
    """Add a token warning and optionally truncate list data."""
    effective_budget = budget or _DEFAULT_TOKEN_BUDGET
    estimated = _estimate_tokens(response_dict)
    if estimated <= effective_budget:
        return response_dict

    meta = response_dict.setdefault("metadata", {})
    meta["estimated_tokens"] = estimated
    meta["token_warning"] = (
        f"Response is ~{estimated} tokens (budget: {effective_budget}). "
        "Consider using pagination or filters to reduce size."
    )

    # Truncate list data if the data payload is a dict with a list value
    data = response_dict.get("data")
    if isinstance(data, Mapping):
        for _key, value in data.items():
            if isinstance(value, list) and len(value) > 1:
                total = len(value)
                value[:] = value[: max(total // 2, 1)]
                meta["truncated"] = True
                meta["total_available"] = total
                meta["returned_count"] = len(value)
                break

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
    return {"data": format_as_markdown_table([]), "metadata": {"format": "markdown"}}


__all__ = [
    "RateLimitError",
    "RateLimiter",
    "SENSITIVE_KEYWORDS",
    "as_tool_response",
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

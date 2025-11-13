"""Utility helpers shared by MCP tools."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any, cast

from automox_mcp.client import AutomoxAPIError
from automox_mcp.schemas import PaginationMetadata, ToolResponse


class RateLimitError(RuntimeError):
    """Raised when a tool exceeds the configured rate limit."""


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


_RATE_LIMITERS: dict[str, RateLimiter] = {
    "console": RateLimiter(name="Automox console API", max_calls=30, period_seconds=60.0),
    "policyreport": RateLimiter(
        name="Automox policy report API", max_calls=20, period_seconds=60.0
    ),
}
_DEFAULT_LIMITER = RateLimiter(name="Automox API", max_calls=30, period_seconds=60.0)


async def enforce_rate_limit(api: str | None = None) -> None:
    """Ensure the current invocation does not exceed per-API rate limits."""
    key = (api or "").strip().lower() or "console"
    limiter = _RATE_LIMITERS.get(key, _DEFAULT_LIMITER)
    await limiter.acquire()


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
            if any(sensitive in lower_key for sensitive in ("token", "secret", "key", "password")):
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
    """Format an AutomoxAPIError for display to the user."""
    payload = exc.payload or {}
    safe_payload = _sanitize_error_payload(payload)
    if not safe_payload and payload:
        safe_payload = _redact_sensitive_fields(payload)
    try:
        payload_block = json.dumps(safe_payload, indent=2, sort_keys=True) if safe_payload else None
    except TypeError:
        payload_block = repr(safe_payload)
    payload_text = payload_block or "No additional details"
    return f"{str(exc)} (status={exc.status_code})\n\nAPI Response:\n{payload_text}"


def as_tool_response(result: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a workflow result to a standardized tool response."""
    metadata_input = result.get("metadata") or {}
    if not isinstance(metadata_input, Mapping):
        metadata_input = {}
    data = result.get("data")
    metadata = PaginationMetadata(**metadata_input)
    response = ToolResponse(data=data, metadata=metadata)
    return cast(dict[str, Any], response.model_dump())


__all__ = [
    "RateLimitError",
    "RateLimiter",
    "as_tool_response",
    "enforce_rate_limit",
    "format_error",
]

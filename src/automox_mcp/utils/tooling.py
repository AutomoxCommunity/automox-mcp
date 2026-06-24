"""Utility helpers shared by MCP tools."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, TypeAlias, cast

from fastmcp.tools import ToolResult
from pydantic import BaseModel

from ..client import AutomoxAPIError
from ..middleware import get_correlation_id
from ..schemas import PaginationMetadata, ToolResponse
from .sanitize import is_sanitization_enabled, sanitize_dict, sanitize_for_llm

logger = logging.getLogger(__name__)

#: Return type of read tools that may render markdown. Either a plain
#: ``{data, metadata}`` envelope (FastMCP wraps it as ``structuredContent``), or a
#: :class:`~fastmcp.tools.ToolResult` carrying both the markdown text (``content``,
#: for human-facing hosts) and the structured object (``structured_content``, for
#: schema-aware hosts / MCP Apps). See :func:`maybe_format_markdown` (issue #177).
ToolReturn: TypeAlias = ToolResult | dict[str, Any]

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
        "splashtop",
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


def is_remediation_allowed() -> bool:
    """Return True when remediation execution is explicitly enabled.

    Gated by ``AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS`` (default off). Controls the
    ``apply_remediation_actions`` tool, which immediately patches/runs worklets
    on endpoints — opt-in even when write mode is enabled.
    """
    value = os.environ.get("AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_splashtop_bulk_allowed() -> bool:
    """Return True when fleet-scale Splashtop client deployment is explicitly enabled.

    Gated by ``AUTOMOX_MCP_ALLOW_SPLASHTOP_BULK_INSTALL_UNINSTALL`` (default
    off). Controls the ``splashtop_bulk_install_uninstall`` tool, which
    installs/uninstalls the Splashtop RMM client across an entire server group
    in one call — a fleet-scale change that per-call confirmation cannot
    meaningfully vet, so it is opt-in even when write mode is enabled. The flag
    name mirrors the tool: this gates *deploying/removing the client software*
    fleet-wide, not starting remote-control sessions (that is
    ``splashtop_initiate_connection``, which is not env-gated). Single-device
    Splashtop actions (install/uninstall/force-disconnect one device) remain
    confirmation-gated only, not env-gated.
    """
    value = os.environ.get("AUTOMOX_MCP_ALLOW_SPLASHTOP_BULK_INSTALL_UNINSTALL", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_upload_policy_file_allowed() -> bool:
    """Return True when local-file installer upload is explicitly enabled.

    Gated by ``AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE`` (default off). Controls the
    ``upload_policy_file`` tool, which reads an installer **from the local
    filesystem** and uploads it to a Required Software policy. Because it reads
    local files, it is opt-in, restricted to a directory allowlist
    (``AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS``), and **local-transport only** — see
    ``utils/upload.py`` and the stdio guard in ``__init__.py`` /
    ``policy_tools.py``.
    """
    value = os.environ.get("AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_stdio_transport() -> bool:
    """Return True when the configured transport is stdio (local).

    Reads ``AUTOMOX_MCP_TRANSPORT`` (default ``stdio``). This is a best-effort
    registration-time check; the authoritative local-only guarantee for
    ``upload_policy_file`` is enforced in ``main()`` (which refuses to start a
    non-stdio transport while the upload flag is on) so a CLI ``--transport``
    flag cannot diverge from it.

    Caveat: the ``main()`` guarantee covers the CLI entrypoint. Code that embeds
    the module-level ``mcp`` server and calls ``mcp.run(transport=...)`` directly
    (bypassing ``main()``) is responsible for its own transport choice — set
    ``AUTOMOX_MCP_TRANSPORT`` accordingly so this registration check still holds.
    """
    value = os.environ.get("AUTOMOX_MCP_TRANSPORT", "").strip().lower()
    return value in {"", "stdio"}


def is_device_deletion_allowed() -> bool:
    """Return True when device deletion is explicitly enabled.

    Gated by ``AUTOMOX_MCP_ALLOW_DELETE_DEVICE`` (default off). Controls the
    ``delete_device`` tool (``DELETE /servers/{id}``), which permanently
    destroys a device record and its history. There is no create-device
    counterpart (agents self-register), so a wrongly deleted record is not
    reconstructable through the MCP and per-call confirmation cannot restore it
    — opt-in even when write mode is enabled (category B, see
    ``docs/api-coverage.md``).
    """
    value = os.environ.get("AUTOMOX_MCP_ALLOW_DELETE_DEVICE", "")
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

    async def reserve(self, request_id: str, tool_name: str) -> tuple[bool, dict[str, Any] | None]:
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

    async def release(self, request_id: str, tool_name: str) -> None:
        """Release an in-flight reservation without storing a response.

        Used on the failure path of a write tool so that the next retry with the
        same ``request_id`` can proceed instead of being shadowed by the in-flight
        sentinel for the cache TTL. Only clears the slot if it is still holding
        the sentinel — a completed entry (a successful store from a parallel
        worker) is preserved.
        """
        async with self._lock:
            key = (request_id, tool_name)
            entry = self._cache.get(key)
            if entry is not None and entry[0] == _SENTINEL_IN_FLIGHT:
                del self._cache[key]

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


async def release_idempotency(request_id: str | None, tool_name: str) -> None:
    """Release an in-flight reservation when a write tool fails before storing.

    Without this, a transient upstream failure leaves the sentinel in place for
    the full TTL, locking out every retry that reuses the same ``request_id``.
    """
    if not request_id:
        return
    await _IDEMPOTENCY_CACHE.release(request_id, tool_name)


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
    # Scrub attacker-controlled string values BEFORE JSON serialization. After
    # json.dumps(indent=2), each value sits behind `  "key": "` on its line, so
    # the line-anchored instruction-prefix regex no longer matches embedded
    # injections like `IMPORTANT: ...`. Sanitizing first puts each value at its
    # own logical line start where the anchor can fire.
    if is_sanitization_enabled() and safe_payload:
        safe_payload = sanitize_dict(safe_payload)
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

    Mutates ``response_dict`` in place. The sole production caller
    (``as_tool_response``) always supplies a freshly built dict — there is no
    cache or shared structure to protect — so the earlier deep copy was wasted
    work on the largest responses.
    """
    effective_budget = budget if budget is not None else _DEFAULT_TOKEN_BUDGET
    estimated = _estimate_tokens(response_dict)
    if estimated <= effective_budget:
        return response_dict

    meta = response_dict.setdefault("metadata", {})
    meta["estimated_tokens"] = estimated
    meta["token_warning"] = (
        f"Response is ~{estimated} tokens (budget: {effective_budget}). "
        "Consider using pagination or filters to reduce size."
    )

    # Truncate list data if the data payload contains a list.
    # When `data` is a dict with several lists, earlier revisions summed
    # `total_available` across every truncated list, which masked which
    # array had been shrunk to what (e.g., `truncated=true,
    # total_available=8` while `data.patch_policy_schedules` held only 4
    # entries — bug #14 from issue #43). The per-key `truncations` map
    # makes the breakdown unambiguous.
    data = response_dict.get("data")
    if isinstance(data, list) and len(data) > 1:
        total = len(data)
        response_dict["data"] = data[: max(total // 2, 1)]
        meta["truncated"] = True
        meta["total_available"] = total
        meta["returned_count"] = len(response_dict["data"])
        meta["truncations"] = {"data": {"total": total, "returned": len(response_dict["data"])}}
        _reconcile_after_truncation(meta, returned=len(response_dict["data"]))
    elif isinstance(data, dict):
        # Truncate ALL oversized lists in the mapping, not just the first.
        truncations: dict[str, dict[str, int]] = {}
        for _key, value in data.items():
            if isinstance(value, list) and len(value) > 1:
                total = len(value)
                data[_key] = value[: max(total // 2, 1)]
                truncations[_key] = {
                    "total": total,
                    "returned": len(data[_key]),
                }
        if truncations:
            meta["truncated"] = True
            meta["truncations"] = truncations
            # `total_available` is the sum of pre-truncation sizes across
            # every truncated list. Retained for backwards-compat with
            # earlier consumers; new code should read `truncations` for
            # per-key counts.
            meta["total_available"] = sum(t["total"] for t in truncations.values())
            # Reconcile sibling scalar count fields (e.g. `<x>_returned`,
            # `total_<x>`, `total_devices`) that still equal the pre-truncation
            # length down to the shrunk length so no count overstates what's
            # present. Use the largest surviving list as the post-truncation
            # reference length.
            max_returned = max(t["returned"] for t in truncations.values())
            _reconcile_sibling_counts(data, truncations=truncations, fallback_len=max_returned)
            _reconcile_after_truncation(meta, returned=max_returned)

    return response_dict


# Conventional sibling scalar count keys (suffix / prefix patterns) that travel
# alongside a list in `data` and report its length. After truncation these would
# overstate the shrunk list, so they are reconciled down. A full cursor /
# suggested_next_call continuation is a follow-up (out of scope here).
_COUNT_KEY_SUFFIXES = ("_returned", "_count")
_COUNT_KEY_PREFIXES = ("total_",)


def _count_key_base(key: str) -> str | None:
    """Return the list name a count key references, or ``None`` if it isn't one.

    ``total_devices`` -> ``devices``; ``events_returned`` -> ``events``;
    ``groups_count`` -> ``groups``. A bare ``total``/``count`` yields ``""``.
    """
    for suffix in _COUNT_KEY_SUFFIXES:
        if key.endswith(suffix):
            return key[: -len(suffix)]
    for prefix in _COUNT_KEY_PREFIXES:
        if key.startswith(prefix):
            return key[len(prefix) :]
    return None


def _reconcile_sibling_counts(
    data: dict[str, Any],
    *,
    truncations: dict[str, dict[str, int]],
    fallback_len: int,
) -> None:
    """Clamp conventional scalar count fields in *data* to their list's length.

    A count key is clamped to the surviving length of the specific list it names
    (e.g. ``total_devices`` -> ``data['devices']``); a generic count that names
    no single list falls back to the largest surviving list. Only ints that
    currently *overstate* their reference length are lowered; legitimately
    smaller counts are left untouched.
    """
    for key, value in data.items():
        if not isinstance(value, int) or isinstance(value, bool):
            continue
        base = _count_key_base(key)
        if base is None:
            continue
        limit = truncations[base]["returned"] if base in truncations else fallback_len
        if value > limit:
            data[key] = limit


def _reconcile_after_truncation(meta: dict[str, Any], *, returned: int) -> None:
    """Ensure a truncated response never signals completeness.

    When items were dropped, a ``metadata.pagination`` block must not assert the
    page is complete: force ``has_more=True`` and clear any ``last=True`` (Spring
    completeness flag) so the response cannot simultaneously claim completeness
    and be truncated.
    """
    pagination = meta.get("pagination")
    if isinstance(pagination, dict):
        pagination["has_more"] = True
        if pagination.get("last") is True:
            pagination["last"] = False


def _coerce_optional_int(value: Any) -> int | None:
    """Coerce *value* to ``int`` when possible, else ``None``.

    Booleans are rejected (``True``/``False`` are not meaningful counts) and
    empty/garbage strings degrade to ``None`` instead of raising.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
    # Defensively coerce every strictly-typed reserved pagination key. Upstream
    # metadata can forward a non-int value (e.g. "" or a string) into any of
    # these; PaginationMetadata types them as int|None, so a raw value would
    # raise a ValidationError here — outside call_tool_workflow's try/except —
    # bypassing the format_validation_error sanitizer and crashing the tool.
    # Degrade a non-coercible value to None rather than raise.
    for _key in ("current_page", "total_pages", "total_count", "limit"):
        if _key in metadata_dict:
            metadata_dict[_key] = _coerce_optional_int(metadata_dict[_key])
    metadata = PaginationMetadata(**metadata_dict)
    response = ToolResponse(data=data, metadata=metadata)
    response_dict = cast(dict[str, Any], response.model_dump())
    if is_sanitization_enabled():
        response_dict = sanitize_dict(response_dict)
    return _apply_token_budget(response_dict)


def format_as_markdown_table(data: list[Any], *, max_col_width: int = 40) -> str:
    """Convert a list of flat dicts into a Markdown table string.

    Robust to non-dict rows: a list of scalars (e.g. UUID/name strings from
    ``list_searches_for_device`` / ``device_search_typeahead``) renders as a
    single ``value`` column rather than raising ``AttributeError`` on
    ``row.get`` (the crash would propagate outside ``call_tool_workflow``'s
    try/except and take down the tool).
    """
    if not data:
        return "_No data_"

    def _cell(value: Any) -> str:
        text = str(value) if value is not None else ""
        if len(text) > max_col_width:
            text = text[: max_col_width - 3] + "..."
        return text.replace("|", "\\|")

    # Scalar rows (no dicts) → single-column table.
    if not any(isinstance(row, Mapping) for row in data):
        header = "| value |"
        separator = "| --- |"
        rows = ["| " + _cell(row) + " |" for row in data]
        return "\n".join([header, separator, *rows])

    # Collect all keys preserving insertion order (dict rows only).
    columns: list[str] = []
    seen: set[str] = set()
    for row in data:
        if not isinstance(row, Mapping):
            continue
        for key in row:
            if key not in seen:
                columns.append(key)
                seen.add(key)

    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"

    rows = []
    for row in data:
        if isinstance(row, Mapping):
            cells = [_cell(row.get(col)) for col in columns]
        else:
            # Non-dict row in a mixed list: place its scalar in the first column.
            cells = [_cell(row)] + ["" for _ in columns[1:]]
        rows.append("| " + " | ".join(cells) + " |")

    return "\n".join([header, separator, *rows])


def maybe_format_markdown(result: dict[str, Any], output_format: str | None) -> ToolReturn:
    """Render the first list in *data* as a markdown table when *output_format* is ``"markdown"``.

    In markdown mode, returns a FastMCP :class:`~fastmcp.tools.ToolResult` whose
    ``content`` is the rendered table (what human-facing hosts display) and whose
    ``structured_content`` is the **full original** ``{data, metadata}`` envelope
    (what schema-aware hosts / MCP Apps consume, and what FastMCP validates against
    the tool's ``output_schema``). This is what lets a read tool advertise an object
    ``output_schema`` *and* still offer markdown — the structured object is never
    replaced by a string (issue #177). Previously this returned
    ``{"data": "<markdown string>", ...}``, which could not satisfy an object schema.

    Returns the original *result* dict unchanged when the format is not markdown, or
    when there is no non-empty list in *data* to tabulate.
    """
    if output_format != "markdown":
        return result
    data = result.get("data", {})
    if isinstance(data, Mapping):
        for _key, value in data.items():
            if isinstance(value, list) and value:
                table = format_as_markdown_table(value)
                return ToolResult(content=table, structured_content=result)
    # Nothing to tabulate — return the structured envelope unchanged.
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
    "ToolResult",
    "ToolReturn",
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

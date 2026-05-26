"""Shared response-handling helpers for workflow modules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def extract_list(response: Any) -> list[Mapping[str, Any]]:
    """Normalize an Automox API response into a list of mappings.

    Handles three common shapes returned by the API:
    - A bare list of records.
    - A dict with a ``"data"`` key containing a list.
    - A single dict record (wrapped in a one-element list).
    """
    if isinstance(response, Sequence) and not isinstance(response, (str, bytes)):
        return [item for item in response if isinstance(item, Mapping)]
    if isinstance(response, Mapping):
        data = response.get("data")
        if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
            return [item for item in data if isinstance(item, Mapping)]
        return [response]
    return []


def normalize_status(value: Any, *, _depth: int = 0) -> str:
    """Normalize policy/device status values to a consistent format.

    Accepts strings, mappings (extracts a nested status key), and
    sequences (returns ``"mixed"`` when statuses differ).
    """
    _MAX_STATUS_DEPTH = 20
    if _depth > _MAX_STATUS_DEPTH:
        return "unknown"

    if value in (None, "", [], {}):
        return "unknown"

    if isinstance(value, Mapping):
        for key in ("status", "policy_status", "result_status", "state"):
            inner = value.get(key)
            if inner not in (None, "", [], {}):
                return normalize_status(inner, _depth=_depth + 1)
        return "unknown"

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        statuses: list[str] = []
        for item in value:
            normalized = normalize_status(item, _depth=_depth + 1)
            if normalized != "unknown":
                statuses.append(normalized)
        if not statuses:
            return "unknown"
        unique_statuses = set(statuses)
        if len(unique_statuses) == 1:
            return next(iter(unique_statuses))
        return "mixed"

    status = str(value).strip().lower()
    if not status:
        return "unknown"
    if any(ch in status for ch in "{}[]"):
        return "mixed"
    if status in {"success", "succeeded", "completed", "complete"}:
        return "success"
    if status in {"partial", "partial_success"}:
        return "partial"
    if "fail" in status or "error" in status:
        return "failed"
    if "cancel" in status:
        return "cancelled"
    return status


def build_pagination_metadata(
    *,
    page: int | None = None,
    page_size: int | None = None,
    total_elements: int | None = None,
    total_pages: int | None = None,
    has_more: bool | None = None,
    next_cursor: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical ``metadata.pagination`` block.

    Every paginated tool in the project emits pagination state under this
    key with the same field names so generic callers can paginate without
    per-tool special-cases (issue #52).

    Fields:
        page          0-indexed page number on offset pagination.
        page_size     Records-per-page (alias for ``limit``).
        total_elements Total records across all pages (when knowable).
        total_pages   Derived from ``total_elements`` and ``page_size``
                      when both are known; can be passed explicitly when
                      the upstream API supplies it.
        has_more      ``True`` when another page is available. Derived
                      from ``total_elements``/``page``/``page_size`` when
                      not explicitly passed.
        next_cursor   Opaque cursor value for cursor-based pagination.

    Anything else relevant to a specific tool (e.g. ``offset``, ``sort``,
    Spring ``first``/``last``) can be merged in via ``extra``. Only
    non-``None`` values are emitted.
    """
    block: dict[str, Any] = {}
    if page is not None:
        block["page"] = page
    if page_size is not None:
        block["page_size"] = page_size
    if total_elements is not None:
        block["total_elements"] = total_elements
        if total_pages is None and page_size and page_size > 0:
            total_pages = (total_elements + page_size - 1) // page_size
    if total_pages is not None:
        block["total_pages"] = total_pages
    if (
        has_more is None
        and total_elements is not None
        and page is not None
        and page_size
        and page_size > 0
    ):
        has_more = (page + 1) * page_size < total_elements
    if has_more is not None:
        block["has_more"] = bool(has_more)
    if next_cursor is not None:
        block["next_cursor"] = next_cursor
    if extra:
        for key, value in extra.items():
            if value is not None and key not in block:
                block[key] = value
    return block


def require_org_id(
    client: Any,
    org_id: int | None = None,
) -> int:
    """Resolve and return the effective org_id, or raise ``ValueError``.

    Prefers *org_id* when given, falling back to ``client.org_id``
    (sourced from ``AUTOMOX_ORG_ID``).
    """
    resolved = org_id if org_id is not None else getattr(client, "org_id", None)
    if resolved is None:
        raise ValueError("org_id required - pass explicitly or set AUTOMOX_ORG_ID")
    return resolved

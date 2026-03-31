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

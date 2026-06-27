"""Data extract workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient

# Shared legend for data-extract projections. Vocab/semantics are attributed to
# the Console API DataExtract schema; the only live-observed status in the
# 2026-06-05 read-only probe was "expired". The download-availability claim is
# spec-derived plus the has_download_url signal (no cardinality claim is baked
# in here — the authoritative phase-2 probe file records download link expiry as
# null on expired records, so download_expires_at being set is NOT a reliable
# "link is live" signal; has_download_url is the reliable one).
_EXTRACT_FIELD_NOTES: dict[str, str] = {
    "status": (
        "Per spec enum: queued | running | complete | failed | canceled | "
        "expired. 'complete' is the downloadable state. Prefer the is_completed "
        "boolean over parsing this string for readiness."
    ),
    "is_completed": (
        "Boolean readiness oracle from the API. true = the extract job finished. "
        "Use this instead of interpreting the status string."
    ),
    "download_expires_at": (
        "Per spec, the ISO 8601 timestamp at which the download link expires. A "
        "set value does NOT by itself mean the link is currently usable. The "
        "reliable can-download signal is has_download_url: when it is "
        "absent/false the CSV cannot be downloaded (download_url is null)."
    ),
}


async def list_data_extracts(
    client: AutomoxClient,
    *,
    org_id: int,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List available data extracts for the organization."""
    params: dict[str, Any] = {"o": org_id}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    response = await client.get("/data-extracts", params=params)

    # Live GET /data-extracts returns a {"results": [...], "size": N} envelope
    # (Spring-style, same class as the approvals fix in #154), NOT a bare list.
    # Extract "results" FIRST so the envelope dict never reaches the single-row
    # wrap below; use "in" (not truthiness) so an empty results [] is preserved.
    if isinstance(response, Mapping) and "results" in response:
        total: int | None = response.get("size")
        raw = response.get("results")
    else:
        total = None
        raw = response
    if not isinstance(raw, list):
        raw = [raw] if isinstance(raw, Mapping) else []

    extracts: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        entry: dict[str, Any] = {
            "id": item.get("id"),
            "status": item.get("status"),
            "is_completed": item.get("is_completed"),
        }
        for optional in ("type", "created_at", "download_expires_at", "parameters"):
            val = item.get(optional)
            if val is not None:
                entry[optional] = val
        # V-155: Flag download_url presence without exposing presigned tokens.
        # has_download_url is the reliable can-download signal (see field_notes).
        if item.get("download_url"):
            entry["has_download_url"] = True
        extracts.append(entry)

    # Pagination honesty: `total_extracts` is a true grand total ONLY when the
    # `{results, size}` envelope supplies `size`. On the bare-list fallback there
    # is no upstream total, so labelling the page length `total_extracts` would
    # overstate a single page as the whole set — emit `extracts_returned` instead.
    data: dict[str, Any] = {
        "extracts_returned": len(extracts),
        "extracts": extracts,
    }
    if isinstance(total, int):
        data["total_extracts"] = total
    else:
        # Deprecated alias: a non-envelope caller historically read
        # `total_extracts` and got the per-page count. Keep it (equal to
        # `extracts_returned`) so existing readers don't break; prefer
        # `extracts_returned` for the honest per-page count.
        data["total_extracts"] = len(extracts)

    return {
        "data": data,
        "metadata": {
            "deprecated_endpoint": False,
            "field_notes": _EXTRACT_FIELD_NOTES,
        },
    }


async def get_data_extract(
    client: AutomoxClient,
    *,
    org_id: int,
    extract_id: str,
) -> dict[str, Any]:
    """Get details and download info for a specific data extract."""
    result = await client.get(f"/data-extracts/{extract_id}", params={"o": org_id})

    if not isinstance(result, Mapping):
        result = {}

    detail: dict[str, Any] = {
        "id": result.get("id"),
        "status": result.get("status"),
        "is_completed": result.get("is_completed"),
    }
    # Real DataExtract fields (per spec + 2026-06-05 live probe). The previously
    # read keys "expires_at"/"file_size"/"row_count"/"updated_at"/"name" do not
    # exist in the DTO or in any live record; download_expires_at is the real
    # link-expiry key.
    for optional in ("type", "created_at", "download_expires_at", "parameters"):
        val = result.get(optional)
        if val is not None:
            detail[optional] = val
    # V-155: Flag download_url presence without exposing presigned tokens to LLM.
    # Presigned URLs contain embedded auth credentials that should not be
    # cached in LLM context. The user can retrieve the URL directly from the
    # Automox console. has_download_url is the reliable can-download signal.
    if result.get("download_url"):
        detail["has_download_url"] = True

    return {
        "data": detail,
        "metadata": {
            "deprecated_endpoint": False,
            "field_notes": _EXTRACT_FIELD_NOTES,
        },
    }


async def create_data_extract(
    client: AutomoxClient,
    *,
    org_id: int,
    extract_data: dict[str, Any],
) -> dict[str, Any]:
    """Request a new data extract."""
    result = await client.post(
        "/data-extracts",
        params={"o": org_id},
        json_data=extract_data,
    )

    # Per spec, POST /data-extracts returns an ARRAY of DataExtract (the created
    # job is element [0]); unverified live (creating an extract is a write, out
    # of scope for this read-only fix). Handle both the array and a single
    # mapping defensively, falling back to {} otherwise.
    if isinstance(result, list):
        result = result[0] if result and isinstance(result[0], Mapping) else {}
    elif not isinstance(result, Mapping):
        result = {}

    return {
        "data": {
            # No out-of-enum "pending" default: the API never returns "pending"
            # (status is the spec enum, e.g. "queued"); fall back to None rather
            # than inventing a value.
            "id": result.get("id"),
            "status": result.get("status"),
            "is_completed": result.get("is_completed"),
            "message": "Data extract request submitted.",
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }

"""Package workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..client import AutomoxClient
from ..utils.pagination import parallel_paginate

# `/servers/{id}/packages` returns a bare list with no `total` field and pages
# 0-indexed by `limit`. A single call therefore silently truncates at the page
# size and the caller cannot tell more pages exist — so by default we walk
# every page until a short one. The cap bounds a runaway loop: 20 × 500 =
# 10 000 packages, comfortably above any real host's inventory.
_DEFAULT_PACKAGE_PAGE_SIZE = 500
_MAX_PACKAGE_PAGES = 20


def _coerce_package_list(raw: Any) -> list[Any]:
    """Normalize a `/servers/{id}/packages` response into a list of packages."""
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return list(raw)
    if isinstance(raw, Mapping):
        data = raw.get("data")
        return list(data) if isinstance(data, list) else []
    return []


async def list_device_packages(
    client: AutomoxClient,
    *,
    org_id: int,
    device_id: int,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List software packages installed on a specific device.

    Default behavior auto-paginates the full installed-package set so callers
    asking "is X installed?" get a complete, non-truncated answer. Passing an
    explicit ``page`` returns just that single 0-indexed page (``limit``
    controls the page size, default 500), for callers that page deliberately.
    """
    page_size = _DEFAULT_PACKAGE_PAGE_SIZE
    if limit is not None:
        page_size = max(1, min(limit, _DEFAULT_PACKAGE_PAGE_SIZE))

    packages: list[Any]
    auto_paginated = page is None
    if page is not None:
        params: dict[str, Any] = {"o": org_id, "page": page, "limit": page_size}
        raw_response = await client.get(f"/servers/{device_id}/packages", params=params)
        packages = _coerce_package_list(raw_response)
    else:

        async def _fetch_page(page_num: int) -> Sequence[Any]:
            page_params = {"o": org_id, "page": page_num, "limit": page_size}
            return _coerce_package_list(
                await client.get(f"/servers/{device_id}/packages", params=page_params)
            )

        packages = await parallel_paginate(
            _fetch_page,
            page_size=page_size,
            max_pages=_MAX_PACKAGE_PAGES,
        )

    total = len(packages)
    summary: list[dict[str, Any]] = []
    for pkg in packages:
        if not isinstance(pkg, Mapping):
            continue
        entry: dict[str, Any] = {
            "id": pkg.get("id"),
            "name": pkg.get("display_name") or pkg.get("name"),
            "version": pkg.get("version"),
            "installed": pkg.get("installed"),
            "repo": pkg.get("repo"),
        }
        severity = pkg.get("severity")
        if severity is not None:
            entry["severity"] = severity
        patch_status = pkg.get("status") or pkg.get("patch_status")
        if patch_status is not None:
            entry["patch_status"] = patch_status
        is_managed = pkg.get("is_managed")
        if is_managed is not None:
            entry["is_managed"] = is_managed
        summary.append(entry)

    metadata: dict[str, Any] = {"deprecated_endpoint": False}
    if auto_paginated:
        # The auto-paginate path walked every page; the count is exhaustive
        # unless we hit the safety cap (a host with >10k packages).
        metadata["complete"] = len(packages) < _MAX_PACKAGE_PAGES * page_size
    else:
        # Single explicit page: a full page means more may exist. The upstream
        # returns no total, so this is the only truncation signal available.
        metadata["pagination"] = {
            "page": page,
            "page_size": page_size,
            "has_more": total >= page_size,
        }

    return {
        "data": {
            "device_id": device_id,
            "total_packages": total,
            "packages": summary,
        },
        "metadata": metadata,
    }


async def search_org_packages(
    client: AutomoxClient,
    *,
    org_id: int,
    include_unmanaged: bool | None = None,
    awaiting: bool | None = None,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Search packages across the organization."""
    params: dict[str, Any] = {}
    if include_unmanaged is not None:
        params["includeUnmanaged"] = 1 if include_unmanaged else 0
    if awaiting is not None:
        params["awaiting"] = 1 if awaiting else 0
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit

    raw_response = await client.get(f"/orgs/{org_id}/packages", params=params)

    packages: list[Any]
    total: int
    if isinstance(raw_response, Mapping):
        packages = (
            raw_response.get("data", []) if isinstance(raw_response.get("data"), list) else []
        )
        total = raw_response.get("total", len(packages))
    elif isinstance(raw_response, list):
        packages = raw_response
        total = len(packages)
    else:
        packages = []
        total = 0
    summary: list[dict[str, Any]] = []
    for pkg in packages:
        if not isinstance(pkg, Mapping):
            continue
        entry: dict[str, Any] = {
            "id": pkg.get("id"),
            "name": pkg.get("display_name") or pkg.get("name"),
            "version": pkg.get("version"),
            "severity": pkg.get("severity"),
        }
        device_count = pkg.get("device_count")
        if device_count is not None:
            entry["device_count"] = device_count
        is_managed = pkg.get("is_managed")
        if is_managed is not None:
            entry["is_managed"] = is_managed
        awaiting_flag = pkg.get("awaiting")
        if awaiting_flag is not None:
            entry["awaiting"] = awaiting_flag
        summary.append(entry)

    return {
        "data": {
            "total_packages": total,
            "packages": summary,
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }

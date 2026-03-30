"""Device inventory workflows for Automox MCP."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from ..client import AutomoxAPIError, AutomoxClient
from ..utils import resolve_org_uuid
from ..utils.response import require_org_id

logger = logging.getLogger(__name__)


async def _resolve_device_uuid(
    client: AutomoxClient,
    *,
    device_id: int,
    org_id: int,
) -> str | None:
    """Look up a device's UUID from its numeric ID."""
    params = {"o": org_id}
    try:
        response = await client.get(f"/servers/{device_id}", params=params)
        if isinstance(response, Mapping):
            return str(response.get("uuid") or response.get("device_uuid") or "") or None
    except AutomoxAPIError as exc:
        logger.debug("Failed to resolve UUID for device %s: %s", device_id, exc)
    return None


async def get_device_inventory(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    device_id: int,
    category: str | None = None,
) -> dict[str, Any]:
    """Retrieve device inventory data from the device-details API.

    Uses org UUID + device UUID to call the Console API inventory endpoint.
    Optionally filter by category (Hardware, Health, Network, Security,
    Services, Summary, System, Users).
    """
    resolved_org_id = require_org_id(client, org_id)

    results = await asyncio.gather(
        resolve_org_uuid(
            client,
            org_id=resolved_org_id,
            allow_account_uuid=False,
        ),
        _resolve_device_uuid(
            client,
            device_id=device_id,
            org_id=resolved_org_id,
        ),
        return_exceptions=True,
    )
    org_uuid_result, device_uuid_result = results
    if isinstance(org_uuid_result, BaseException):
        raise org_uuid_result
    if isinstance(device_uuid_result, BaseException):
        raise device_uuid_result
    org_uuid_str: str = org_uuid_result
    device_uuid_str: str | None = device_uuid_result
    if not device_uuid_str:
        raise ValueError(
            f"Could not resolve UUID for device {device_id}. "
            f"The device may not exist in organization {resolved_org_id}."
        )

    path = f"/device-details/orgs/{org_uuid_str}/devices/{device_uuid_str}/inventory"
    params: dict[str, Any] = {}
    if category:
        params["category"] = category

    inventory_raw = await client.get(path, params=params)

    # Parse the nested categories -> sub_categories -> data structure
    categories_data: dict[str, Any] = {}
    if isinstance(inventory_raw, Mapping):
        raw_categories = inventory_raw.get("categories")
        if isinstance(raw_categories, Mapping):
            for cat_name, cat_content in raw_categories.items():
                cat_entry: dict[str, Any] = {
                    "name": cat_name,
                    "sub_categories": {},
                }
                if isinstance(cat_content, Mapping):
                    sub_cats = cat_content.get("sub_categories")
                    if isinstance(sub_cats, Mapping):
                        for sub_name, sub_content in sub_cats.items():
                            items: list[dict[str, Any]] = []
                            if isinstance(sub_content, Mapping):
                                data_items = sub_content.get("data")
                                if isinstance(data_items, Sequence) and not isinstance(
                                    data_items, (str, bytes)
                                ):
                                    for item in data_items:
                                        if isinstance(item, Mapping):
                                            items.append(
                                                {
                                                    "name": item.get("name"),
                                                    "friendly_name": item.get("friendly_name"),
                                                    "value": item.get("value"),
                                                    "type": item.get("type"),
                                                    "collected_at": item.get("collected_at"),
                                                }
                                            )
                            cat_entry["sub_categories"][sub_name] = {
                                "item_count": len(items),
                                "items": items,
                            }
                categories_data[cat_name] = cat_entry

    total_items = sum(
        sub["item_count"]
        for cat in categories_data.values()
        for sub in cat.get("sub_categories", {}).values()
    )

    return {
        "data": {
            "device_id": device_id,
            "device_uuid": device_uuid_str,
            "category_filter": category,
            "total_categories": len(categories_data),
            "total_items": total_items,
            "categories": categories_data,
        },
        "metadata": {
            "deprecated_endpoint": False,
            "org_id": resolved_org_id,
            "org_uuid": org_uuid_str,
            "device_id": device_id,
            "device_uuid": device_uuid_str,
            "category_filter": category,
        },
    }


async def get_device_inventory_categories(
    client: AutomoxClient,
    *,
    org_id: int | None = None,
    device_id: int,
) -> dict[str, Any]:
    """Retrieve available inventory categories for a device."""
    resolved_org_id = require_org_id(client, org_id)

    results = await asyncio.gather(
        resolve_org_uuid(
            client,
            org_id=resolved_org_id,
            allow_account_uuid=False,
        ),
        _resolve_device_uuid(
            client,
            device_id=device_id,
            org_id=resolved_org_id,
        ),
        return_exceptions=True,
    )
    org_uuid_result, device_uuid_result = results
    if isinstance(org_uuid_result, BaseException):
        raise org_uuid_result
    if isinstance(device_uuid_result, BaseException):
        raise device_uuid_result
    org_uuid_str: str = org_uuid_result
    device_uuid_str: str | None = device_uuid_result
    if not device_uuid_str:
        raise ValueError(
            f"Could not resolve UUID for device {device_id}. "
            f"The device may not exist in organization {resolved_org_id}."
        )

    path = f"/device-details/orgs/{org_uuid_str}/devices/{device_uuid_str}/categories"
    categories_raw = await client.get(path)

    categories: list[dict[str, str]] = []
    if isinstance(categories_raw, Sequence) and not isinstance(categories_raw, (str, bytes)):
        for item in categories_raw:
            if isinstance(item, Mapping):
                categories.append(
                    {
                        "name": item.get("name", ""),
                        "friendly_name": item.get("friendly_name", ""),
                    }
                )

    return {
        "data": {
            "device_id": device_id,
            "device_uuid": device_uuid_str,
            "categories": categories,
        },
        "metadata": {
            "deprecated_endpoint": False,
            "org_id": resolved_org_id,
            "org_uuid": org_uuid_str,
            "device_id": device_id,
            "device_uuid": device_uuid_str,
        },
    }


__all__ = [
    "get_device_inventory",
    "get_device_inventory_categories",
]

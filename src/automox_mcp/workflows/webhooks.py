"""Webhook workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..client import AutomoxClient


def _summarize_webhook(webhook: Mapping[str, Any]) -> dict[str, Any]:
    """Extract key fields from a webhook record."""
    return {
        "id": webhook.get("id"),
        "name": webhook.get("name"),
        "url": webhook.get("url"),
        "enabled": webhook.get("enabled"),
        "eventTypes": webhook.get("eventTypes"),
        "createdAt": webhook.get("createdAt"),
        "updatedAt": webhook.get("updatedAt"),
    }


async def list_webhook_event_types(
    client: AutomoxClient,
) -> dict[str, Any]:
    """Retrieve the list of available webhook event types."""
    result = await client.get("/webhooks/event-types")

    data: Any
    if isinstance(result, Mapping):
        data = result
    elif isinstance(result, list):
        data = {"event_types": result}
    else:
        data = {"raw": result}

    return {
        "data": data,
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


async def list_webhooks(
    client: AutomoxClient,
    *,
    org_uuid: str,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List all webhooks for the organization."""
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if cursor is not None:
        params["cursor"] = cursor

    result = await client.get(f"/organizations/{org_uuid}/webhooks", params=params)

    webhooks: list[dict[str, Any]] = []
    next_cursor: str | None = None
    if isinstance(result, Mapping):
        raw_items = result.get("data") or result.get("webhooks") or []
        if isinstance(raw_items, list):
            webhooks = [_summarize_webhook(w) for w in raw_items if isinstance(w, Mapping)]
        next_cursor = result.get("nextCursor") or result.get("next_cursor")
    elif isinstance(result, list):
        webhooks = [_summarize_webhook(w) for w in result if isinstance(w, Mapping)]

    data: dict[str, Any] = {
        "total_webhooks": len(webhooks),
        "webhooks": webhooks,
    }
    if next_cursor:
        data["next_cursor"] = next_cursor

    return {
        "data": data,
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


async def get_webhook(
    client: AutomoxClient,
    *,
    org_uuid: str,
    webhook_id: str,
) -> dict[str, Any]:
    """Retrieve details for a specific webhook."""
    result = await client.get(f"/organizations/{org_uuid}/webhooks/{webhook_id}")

    data: dict[str, Any]
    if isinstance(result, Mapping):
        data = _summarize_webhook(result)
    else:
        data = {"webhook_id": webhook_id, "raw": result}

    return {
        "data": data,
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


async def create_webhook(
    client: AutomoxClient,
    *,
    org_uuid: str,
    name: str,
    url: str,
    event_types: list[str],
) -> dict[str, Any]:
    """Create a new webhook subscription.

    IMPORTANT: The response includes a signing secret that is only shown once.
    """
    body: dict[str, Any] = {
        "name": name,
        "url": url,
        "eventTypes": event_types,
    }

    result = await client.post(f"/organizations/{org_uuid}/webhooks", json_data=body)

    data: dict[str, Any]
    if isinstance(result, Mapping):
        data = {
            "id": result.get("id"),
            "name": result.get("name"),
            "url": result.get("url"),
            "enabled": result.get("enabled"),
            "eventTypes": result.get("eventTypes"),
            "secret": result.get("secret"),
            "createdAt": result.get("createdAt"),
            "_important": (
                "SAVE THE SECRET NOW. The signing secret above is only shown once "
                "and cannot be retrieved later. Store it securely for signature "
                "verification of incoming webhook deliveries."
            ),
        }
    else:
        data = {"created": True, "raw": result}

    return {
        "data": data,
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


async def update_webhook(
    client: AutomoxClient,
    *,
    org_uuid: str,
    webhook_id: str,
    name: str | None = None,
    url: str | None = None,
    enabled: bool | None = None,
    event_types: list[str] | None = None,
) -> dict[str, Any]:
    """Update an existing webhook (partial update)."""
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if url is not None:
        body["url"] = url
    if enabled is not None:
        body["enabled"] = enabled
    if event_types is not None:
        body["eventTypes"] = event_types

    result = await client.put(
        f"/organizations/{org_uuid}/webhooks/{webhook_id}",
        json_data=body,
    )

    data: dict[str, Any]
    if isinstance(result, Mapping):
        data = _summarize_webhook(result)
        data["updated"] = True
    else:
        data = {"webhook_id": webhook_id, "updated": True, "raw": result}

    return {
        "data": data,
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


async def delete_webhook(
    client: AutomoxClient,
    *,
    org_uuid: str,
    webhook_id: str,
) -> dict[str, Any]:
    """Delete a webhook permanently."""
    await client.delete(f"/organizations/{org_uuid}/webhooks/{webhook_id}")

    return {
        "data": {
            "webhook_id": webhook_id,
            "deleted": True,
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


async def test_webhook(
    client: AutomoxClient,
    *,
    org_uuid: str,
    webhook_id: str,
) -> dict[str, Any]:
    """Send a test delivery to a webhook endpoint."""
    result = await client.post(f"/organizations/{org_uuid}/webhooks/{webhook_id}/test")

    data: dict[str, Any]
    if isinstance(result, Mapping):
        data = {
            "webhook_id": webhook_id,
            "success": result.get("success"),
            "statusCode": result.get("statusCode"),
            "responseTime": result.get("responseTime"),
            "tested": True,
        }
    else:
        data = {"webhook_id": webhook_id, "tested": True, "raw": result}

    return {
        "data": data,
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


async def rotate_webhook_secret(
    client: AutomoxClient,
    *,
    org_uuid: str,
    webhook_id: str,
) -> dict[str, Any]:
    """Rotate the signing secret for a webhook.

    IMPORTANT: The old secret is immediately invalidated.
    """
    result = await client.post(
        f"/organizations/{org_uuid}/webhooks/{webhook_id}/secret/rotate",
    )

    data: dict[str, Any]
    if isinstance(result, Mapping):
        data = {
            "webhook_id": webhook_id,
            "secret": result.get("secret"),
            "rotated": True,
            "_important": (
                "SAVE THE NEW SECRET NOW. The old signing secret has been "
                "invalidated. Update your webhook receiver with the new secret "
                "above before processing any new deliveries."
            ),
        }
    else:
        data = {"webhook_id": webhook_id, "rotated": True, "raw": result}

    return {
        "data": data,
        "metadata": {
            "deprecated_endpoint": False,
        },
    }

"""Webhook resources for Automox MCP."""

from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP

# Static reference data from the Automox Webhooks API v1.0.0 spec.
_WEBHOOK_EVENT_TYPES: list[dict[str, Any]] = [
    # Device events
    {"name": "device.created", "category": "device", "description": "A new device was registered."},
    {
        "name": "device.updated",
        "category": "device",
        "description": "Device metadata was modified.",
    },
    {"name": "device.deleted", "category": "device", "description": "A device was removed."},
    {
        "name": "device.detail_updated",
        "category": "device",
        "description": "Device detail information (hardware, OS) was updated.",
    },
    {
        "name": "device.checkin_updated",
        "category": "device",
        "description": "Device check-in status changed.",
    },
    {
        "name": "device.command_executed",
        "category": "device",
        "description": "A command (scan, patch, reboot) was executed on a device.",
    },
    {
        "name": "device.disconnected_extended",
        "category": "device",
        "description": "A device has been disconnected for an extended period.",
    },
    # Policy events
    {"name": "policy.created", "category": "policy", "description": "A new policy was created."},
    {"name": "policy.updated", "category": "policy", "description": "A policy was modified."},
    {"name": "policy.deleted", "category": "policy", "description": "A policy was deleted."},
    {
        "name": "policy.evaluated",
        "category": "policy",
        "description": "A policy was evaluated against devices.",
    },
    {
        "name": "policy.compliant",
        "category": "policy",
        "description": "A device became compliant with a policy.",
    },
    {
        "name": "policy.non_compliant",
        "category": "policy",
        "description": "A device became non-compliant with a policy.",
    },
    {
        "name": "policy.remediation_started",
        "category": "policy",
        "description": "Policy remediation has started on a device.",
    },
    {
        "name": "policy.notification_accepted",
        "category": "policy",
        "description": "A user accepted a policy notification (e.g., reboot prompt).",
    },
    {
        "name": "policy.blocked_remediated",
        "category": "policy",
        "description": "A blocked policy was remediated.",
    },
    # Worklet events
    {
        "name": "worklet.success",
        "category": "worklet",
        "description": "A worklet completed successfully.",
    },
    {
        "name": "worklet.failure",
        "category": "worklet",
        "description": "A worklet execution failed.",
    },
    {
        "name": "worklet.execution_started",
        "category": "worklet",
        "description": "A worklet started executing.",
    },
    # Device group events
    {
        "name": "device_group.created",
        "category": "device_group",
        "description": "A new server group was created.",
    },
    {
        "name": "device_group.updated",
        "category": "device_group",
        "description": "A server group was modified.",
    },
    {
        "name": "device_group.deleted",
        "category": "device_group",
        "description": "A server group was deleted.",
    },
    # Organization events
    {
        "name": "organization.preference_updated",
        "category": "organization",
        "description": "An organization preference was changed.",
    },
    # Audit events
    {"name": "audit.user_logged_in", "category": "audit", "description": "A user logged in."},
    {"name": "audit.user_created", "category": "audit", "description": "A new user was created."},
    {"name": "audit.user_removed", "category": "audit", "description": "A user was removed."},
    {
        "name": "audit.role_created",
        "category": "audit",
        "description": "A new RBAC role was created.",
    },
    {"name": "audit.role_updated", "category": "audit", "description": "An RBAC role was updated."},
    {"name": "audit.role_deleted", "category": "audit", "description": "An RBAC role was deleted."},
    {
        "name": "audit.role_revoked",
        "category": "audit",
        "description": "An RBAC role was revoked from a user.",
    },
    {
        "name": "audit.role_assigned",
        "category": "audit",
        "description": "An RBAC role was assigned to a user.",
    },
    {
        "name": "audit.agent_auto_update_disabled",
        "category": "audit",
        "description": "Automatic agent updates were disabled.",
    },
    {
        "name": "audit.agent_auto_update_enabled",
        "category": "audit",
        "description": "Automatic agent updates were enabled.",
    },
    {
        "name": "audit.release_channel_changed",
        "category": "audit",
        "description": "The agent release channel was changed.",
    },
    {"name": "audit.saml_disabled", "category": "audit", "description": "SAML SSO was disabled."},
    {"name": "audit.saml_enabled", "category": "audit", "description": "SAML SSO was enabled."},
    {
        "name": "audit.api_key_deleted",
        "category": "audit",
        "description": "An API key was deleted.",
    },
    {
        "name": "audit.device_scan_requested",
        "category": "audit",
        "description": "A device scan was requested.",
    },
    {
        "name": "audit.device_reboot_requested",
        "category": "audit",
        "description": "A device reboot was requested.",
    },
]

# Precompute the JSON response once at module load — the data is static.
_categories: dict[str, list[dict[str, str]]] = {}
for _evt in _WEBHOOK_EVENT_TYPES:
    _categories.setdefault(_evt["category"], []).append(
        {"name": _evt["name"], "description": _evt["description"]}
    )
_WEBHOOK_EVENT_TYPES_JSON: str = json.dumps(
    {
        "total_event_types": len(_WEBHOOK_EVENT_TYPES),
        "categories": _categories,
        "notes": (
            "Pass event type names in the 'event_types' parameter when "
            "calling create_webhook or update_webhook. A webhook can "
            "subscribe to multiple event types."
        ),
        "limits": {
            "max_webhooks_per_org": 5,
            "url_protocol": "HTTPS only",
            "max_name_length": 255,
            "delivery_timeout": "3 seconds",
            "retry_attempts": 3,
            "deliveries_per_minute": 100,
        },
    },
    indent=2,
)
del _categories, _evt  # clean up module namespace


def register(server: FastMCP) -> None:
    """Register webhook reference resources."""

    @server.resource(
        "resource://webhooks/event-types",
        name="Webhook Event Types",
        description=(
            "Complete list of all 36 Automox webhook event types with categories "
            "and descriptions. Use this to see which events can trigger webhook "
            "deliveries when creating or updating webhook subscriptions."
        ),
        mime_type="application/json",
    )
    async def webhook_event_types() -> str:
        return _WEBHOOK_EVENT_TYPES_JSON


__all__ = ["register"]

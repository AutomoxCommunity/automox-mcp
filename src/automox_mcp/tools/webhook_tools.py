"""Webhook management tools for Automox MCP."""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field, ValidationError, model_validator

from .. import workflows
from ..client import AutomoxAPIError, AutomoxClient
from ..schemas import ForbidExtraModel
from ..utils import resolve_org_uuid
from ..utils.tooling import (
    RateLimitError,
    as_tool_response,
    check_idempotency,
    enforce_rate_limit,
    format_error,
    maybe_format_markdown,
    store_idempotency,
)


def _validate_webhook_url(url: str) -> None:
    """Validate a webhook URL: HTTPS, no userinfo, no private/internal IPs."""
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError(
            "Webhook URL must use HTTPS with a valid hostname (e.g. https://example.com/webhook)"
        )
    if "@" in (parsed.netloc or ""):
        raise ValueError("Webhook URL must not contain userinfo (user:pass@host)")
    # Block private, loopback, and link-local IP addresses to prevent SSRF relay
    hostname = parsed.hostname
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise ValueError(
                "Webhook URL must not target private, loopback, or link-local addresses"
            )
    except ValueError as exc:
        if "must not target" in str(exc):
            raise
        # Not a bare IP — hostname is fine; DNS resolution is Automox's responsibility
    # Block well-known cloud metadata endpoints by hostname
    _BLOCKED_HOSTS = {
        "metadata.google.internal",
        "metadata.google",
        "metadata.azure.com",
        "management.azure.com",
        "instance-data",
        "metadata.oraclecloud.com",
    }
    lower_host = hostname.lower()
    if lower_host in _BLOCKED_HOSTS or lower_host.endswith(".internal"):
        raise ValueError("Webhook URL must not target cloud metadata endpoints")


def _strip_secret(result: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *result* with any ``secret`` value removed from the data payload.

    Used to avoid caching one-time webhook secrets in the idempotency cache.
    """
    import copy

    safe = copy.deepcopy(result)
    data = safe.get("data")
    if isinstance(data, dict):
        data.pop("secret", None)
    return safe


# -----------------------------------------------------------------
# Webhook-specific Pydantic schemas (not pre-existing in schemas.py)
# -----------------------------------------------------------------


class ListWebhookEventTypesParams(ForbidExtraModel):
    """No parameters needed."""

    pass


class ListWebhooksParams(ForbidExtraModel):
    org_uuid: UUID
    limit: int | None = None
    cursor: str | None = None


class GetWebhookParams(ForbidExtraModel):
    org_uuid: UUID
    webhook_id: UUID


class CreateWebhookParams(ForbidExtraModel):
    org_uuid: UUID
    name: str
    url: str = Field(description="HTTPS webhook endpoint URL")
    event_types: list[str]

    @model_validator(mode="after")
    def _enforce_https(self) -> CreateWebhookParams:
        _validate_webhook_url(self.url)
        return self


class UpdateWebhookParams(ForbidExtraModel):
    org_uuid: UUID
    webhook_id: UUID
    name: str | None = None
    url: str | None = Field(None, description="HTTPS webhook endpoint URL")
    enabled: bool | None = None
    event_types: list[str] | None = None

    @model_validator(mode="after")
    def _enforce_https(self) -> UpdateWebhookParams:
        if self.url is not None:
            _validate_webhook_url(self.url)
        return self


class DeleteWebhookParams(ForbidExtraModel):
    org_uuid: UUID
    webhook_id: UUID


class TestWebhookParams(ForbidExtraModel):
    org_uuid: UUID
    webhook_id: UUID


class RotateWebhookSecretParams(ForbidExtraModel):
    org_uuid: UUID
    webhook_id: UUID


logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register webhook management tools."""

    async def _call(
        func: Callable[..., Awaitable[dict[str, Any]]],
        params_model: type[BaseModel] | None,
        raw_params: dict[str, Any],
        org_uuid_field: str | None = None,
    ) -> dict[str, Any]:
        try:
            await enforce_rate_limit()
            client_org_id = client.org_id
            params = dict(raw_params)
            if org_uuid_field is not None:
                raw_org_id = params.get("org_id")
                resolved_uuid = await resolve_org_uuid(
                    client,
                    explicit_uuid=params.get(org_uuid_field),
                    org_id=raw_org_id if raw_org_id is not None else client_org_id,
                    allow_account_uuid=True,
                )
                params[org_uuid_field] = resolved_uuid
            if params_model is not None:
                model = params_model(**params)
                payload = model.model_dump(mode="python", exclude_none=True)
            else:
                payload = {k: v for k, v in params.items() if v is not None}
            result: dict[str, Any] = await func(client, **payload)
        except (ValidationError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
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

    # ------ Read-only tools (always registered) ------

    @server.tool(
        name="list_webhook_event_types",
        description=(
            "List all available Automox webhook event types with descriptions. "
            "Use this to see which events can trigger webhook deliveries."
        ),
    )
    async def list_webhook_event_types() -> dict[str, Any]:
        return await _call(
            workflows.list_webhook_event_types,
            None,
            {},
        )

    @server.tool(
        name="list_webhooks",
        description=(
            "List all webhook subscriptions for the Automox organization. "
            "Supports cursor-based pagination."
        ),
    )
    async def list_webhooks(
        org_uuid: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "org_uuid": org_uuid,
            "limit": limit,
            "cursor": cursor,
        }
        result = await _call(
            workflows.list_webhooks,
            ListWebhooksParams,
            params,
            org_uuid_field="org_uuid",
        )

        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_webhook",
        description="Retrieve details for a specific Automox webhook subscription.",
    )
    async def get_webhook(
        webhook_id: str,
        org_uuid: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "org_uuid": org_uuid,
            "webhook_id": webhook_id,
        }
        return await _call(
            workflows.get_webhook,
            GetWebhookParams,
            params,
            org_uuid_field="org_uuid",
        )

    # ------ Write tools (gated by read_only) ------

    if not read_only:

        @server.tool(
            name="create_webhook",
            description=(
                "Create a new Automox webhook subscription. The response includes a "
                "signing secret that is ONLY shown once — save it immediately. "
                "Max 5 webhooks per organization. URL must be HTTPS."
            ),
            annotations={"destructiveHint": True},
        )
        async def create_webhook(
            name: str,
            url: str,
            event_types: list[str],
            org_uuid: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "create_webhook")
            if cached is not None:
                return cached

            params = {
                "org_uuid": org_uuid,
                "name": name,
                "url": url,
                "event_types": event_types,
            }
            result = await _call(
                workflows.create_webhook,
                CreateWebhookParams,
                params,
                org_uuid_field="org_uuid",
            )
            # Cache without the one-time secret to avoid keeping it in memory.
            cache_safe = _strip_secret(result)
            await store_idempotency(request_id, "create_webhook", cache_safe)
            return result

        @server.tool(
            name="update_webhook",
            description=(
                "Update an existing Automox webhook. Only provided fields are changed "
                "(partial update). Can update name, URL, enabled status, or event types."
            ),
            annotations={"destructiveHint": True},
        )
        async def update_webhook(
            webhook_id: str,
            org_uuid: str | None = None,
            name: str | None = None,
            url: str | None = None,
            enabled: bool | None = None,
            event_types: list[str] | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "update_webhook")
            if cached is not None:
                return cached

            params = {
                "org_uuid": org_uuid,
                "webhook_id": webhook_id,
                "name": name,
                "url": url,
                "enabled": enabled,
                "event_types": event_types,
            }
            result = await _call(
                workflows.update_webhook,
                UpdateWebhookParams,
                params,
                org_uuid_field="org_uuid",
            )
            await store_idempotency(request_id, "update_webhook", result)
            return result

        @server.tool(
            name="delete_webhook",
            description="Delete an Automox webhook subscription permanently.",
            annotations={"destructiveHint": True},
        )
        async def delete_webhook(
            webhook_id: str,
            org_uuid: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "delete_webhook")
            if cached is not None:
                return cached

            params = {
                "org_uuid": org_uuid,
                "webhook_id": webhook_id,
            }
            result = await _call(
                workflows.delete_webhook,
                DeleteWebhookParams,
                params,
                org_uuid_field="org_uuid",
            )
            await store_idempotency(request_id, "delete_webhook", result)
            return result

        @server.tool(
            name="test_webhook",
            description=(
                "Send a test delivery to an Automox webhook endpoint. "
                "Returns success status, HTTP status code, and response time."
            ),
            annotations={"destructiveHint": True},
        )
        async def test_webhook(
            webhook_id: str,
            org_uuid: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "test_webhook")
            if cached is not None:
                return cached

            params = {
                "org_uuid": org_uuid,
                "webhook_id": webhook_id,
            }
            result = await _call(
                workflows.test_webhook,
                TestWebhookParams,
                params,
                org_uuid_field="org_uuid",
            )
            await store_idempotency(request_id, "test_webhook", result)
            return result

        @server.tool(
            name="rotate_webhook_secret",
            description=(
                "Rotate the signing secret for an Automox webhook. The old secret "
                "is immediately invalidated. Save the new secret — it is only shown once."
            ),
            annotations={"destructiveHint": True},
        )
        async def rotate_webhook_secret(
            webhook_id: str,
            org_uuid: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "rotate_webhook_secret")
            if cached is not None:
                return cached

            params = {
                "org_uuid": org_uuid,
                "webhook_id": webhook_id,
            }
            result = await _call(
                workflows.rotate_webhook_secret,
                RotateWebhookSecretParams,
                params,
                org_uuid_field="org_uuid",
            )
            cache_safe = _strip_secret(result)
            await store_idempotency(request_id, "rotate_webhook_secret", cache_safe)
            return result


__all__ = ["register"]

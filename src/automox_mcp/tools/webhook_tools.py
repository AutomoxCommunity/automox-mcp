"""Webhook management tools for Automox MCP."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
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
    enforce_rate_limit,
    format_error,
)

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
        if not self.url.lower().startswith("https://"):
            raise ValueError("Webhook URL must use HTTPS (e.g. https://example.com/webhook)")
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
        if self.url is not None and not self.url.lower().startswith("https://"):
            raise ValueError("Webhook URL must use HTTPS (e.g. https://example.com/webhook)")
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
            raise ToolError(f"Unexpected error: {type(exc).__name__}: {exc}") from exc
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
    ) -> dict[str, Any]:
        params = {
            "org_uuid": org_uuid,
            "limit": limit,
            "cursor": cursor,
        }
        return await _call(
            workflows.list_webhooks,
            ListWebhooksParams,
            params,

            org_uuid_field="org_uuid",
        )

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
        ) -> dict[str, Any]:
            params = {
                "org_uuid": org_uuid,
                "name": name,
                "url": url,
                "event_types": event_types,
            }
            return await _call(
                workflows.create_webhook,
                CreateWebhookParams,
                params,
    
                org_uuid_field="org_uuid",
            )

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
        ) -> dict[str, Any]:
            params = {
                "org_uuid": org_uuid,
                "webhook_id": webhook_id,
                "name": name,
                "url": url,
                "enabled": enabled,
                "event_types": event_types,
            }
            return await _call(
                workflows.update_webhook,
                UpdateWebhookParams,
                params,
    
                org_uuid_field="org_uuid",
            )

        @server.tool(
            name="delete_webhook",
            description="Delete an Automox webhook subscription permanently.",
            annotations={"destructiveHint": True},
        )
        async def delete_webhook(
            webhook_id: str,
            org_uuid: str | None = None,
        ) -> dict[str, Any]:
            params = {
                "org_uuid": org_uuid,
                "webhook_id": webhook_id,
            }
            return await _call(
                workflows.delete_webhook,
                DeleteWebhookParams,
                params,
    
                org_uuid_field="org_uuid",
            )

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
        ) -> dict[str, Any]:
            params = {
                "org_uuid": org_uuid,
                "webhook_id": webhook_id,
            }
            return await _call(
                workflows.test_webhook,
                TestWebhookParams,
                params,
    
                org_uuid_field="org_uuid",
            )

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
        ) -> dict[str, Any]:
            params = {
                "org_uuid": org_uuid,
                "webhook_id": webhook_id,
            }
            return await _call(
                workflows.rotate_webhook_secret,
                RotateWebhookSecretParams,
                params,
    
                org_uuid_field="org_uuid",
            )


__all__ = ["register"]

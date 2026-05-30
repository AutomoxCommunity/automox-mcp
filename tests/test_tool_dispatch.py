"""Tests for tool dispatch — verifies that each tool's _call inner function
correctly routes to the underlying workflow function.

Pattern: register the tool module against a StubServer (which captures the
tool functions by name in a plain dict), monkeypatch the workflow the tool
calls, invoke the captured function, assert the mock was called.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import FakeClient, StubServer

from automox_mcp.tools import (
    account_tools,
    audit_tools,
    device_tools,
    event_tools,
    group_tools,
    package_tools,
    policy_tools,
    report_tools,
    splashtop_tools,
    vuln_sync_tools,
    webhook_tools,
)
from automox_mcp.utils import tooling as _utils_tooling

# ---------------------------------------------------------------------------
# Shared test infrastructure
# ---------------------------------------------------------------------------


def _success() -> dict[str, Any]:
    return {"data": {}, "metadata": {"deprecated_endpoint": False}}


# ---------------------------------------------------------------------------
# event_tools
# ---------------------------------------------------------------------------


class TestEventToolsDispatch:
    @pytest.mark.asyncio
    async def test_list_events_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake_list_events(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(event_tools.workflows, "list_events", fake_list_events)

        server = StubServer()
        event_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["list_events"](limit=5)

        assert "limit" in recorded
        assert recorded["limit"] == 5

    @pytest.mark.asyncio
    async def test_list_events_passes_filters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake_list_events(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(event_tools.workflows, "list_events", fake_list_events)

        server = StubServer()
        event_tools.register(server, client=FakeClient(org_id=10))

        await server.tools["list_events"](event_name="patch.apply", policy_id=99)

        assert recorded.get("event_name") == "patch.apply"
        assert recorded.get("policy_id") == 99


# ---------------------------------------------------------------------------
# report_tools
# ---------------------------------------------------------------------------


class TestReportToolsDispatch:
    @pytest.mark.asyncio
    async def test_prepatch_report_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[bool] = []

        async def fake_prepatch(client, **kwargs):
            called.append(True)
            return _success()

        monkeypatch.setattr(report_tools.workflows, "get_prepatch_report", fake_prepatch)

        server = StubServer()
        report_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["prepatch_report"]()

        assert called

    @pytest.mark.asyncio
    async def test_noncompliant_report_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: list[bool] = []

        async def fake_noncompliant(client, **kwargs):
            called.append(True)
            return _success()

        monkeypatch.setattr(report_tools.workflows, "get_noncompliant_report", fake_noncompliant)

        server = StubServer()
        report_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["noncompliant_report"](limit=20)

        assert called


# ---------------------------------------------------------------------------
# package_tools
# ---------------------------------------------------------------------------


class TestPackageToolsDispatch:
    @pytest.mark.asyncio
    async def test_list_device_packages_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake_list_pkgs(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(package_tools.workflows, "list_device_packages", fake_list_pkgs)

        server = StubServer()
        package_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["list_device_packages"](device_id=7, limit=50)

        assert recorded.get("device_id") == 7
        assert recorded.get("limit") == 50

    @pytest.mark.asyncio
    async def test_search_org_packages_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake_search(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(package_tools.workflows, "search_org_packages", fake_search)

        server = StubServer()
        package_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["search_org_packages"](awaiting=True)

        assert recorded.get("org_id") == 42


# ---------------------------------------------------------------------------
# group_tools
# ---------------------------------------------------------------------------


class TestGroupToolsDispatch:
    @pytest.mark.asyncio
    async def test_list_server_groups_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[bool] = []

        async def fake_list(client, **kwargs):
            called.append(True)
            return _success()

        monkeypatch.setattr(group_tools.workflows, "list_server_groups", fake_list)

        server = StubServer()
        group_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["list_server_groups"]()

        assert called

    @pytest.mark.asyncio
    async def test_get_server_group_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake_get(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(group_tools.workflows, "get_server_group", fake_get)

        server = StubServer()
        group_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["get_server_group"](group_id=10)

        assert recorded.get("group_id") == 10

    @pytest.mark.asyncio
    async def test_create_server_group_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake_create(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(group_tools.workflows, "create_server_group", fake_create)

        server = StubServer()
        group_tools.register(server, read_only=False, client=FakeClient(org_id=42))

        await server.tools["create_server_group"](
            name="Prod", refresh_interval=360, parent_server_group_id=0
        )

        assert recorded.get("name") == "Prod"
        assert recorded.get("refresh_interval") == 360

    @pytest.mark.asyncio
    async def test_update_server_group_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake_update(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(group_tools.workflows, "update_server_group", fake_update)

        server = StubServer()
        group_tools.register(server, read_only=False, client=FakeClient(org_id=42))

        await server.tools["update_server_group"](
            group_id=10, name="Prod-v2", refresh_interval=720, parent_server_group_id=0
        )

        assert recorded.get("group_id") == 10
        assert recorded.get("name") == "Prod-v2"

    @pytest.mark.asyncio
    async def test_delete_server_group_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake_delete(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(group_tools.workflows, "delete_server_group", fake_delete)

        server = StubServer()
        group_tools.register(server, read_only=False, client=FakeClient(org_id=42))

        await server.tools["delete_server_group"](group_id=10)

        assert recorded.get("group_id") == 10

    @pytest.mark.asyncio
    async def test_write_tools_absent_in_read_only(self) -> None:
        server = StubServer()
        group_tools.register(server, read_only=True, client=FakeClient(org_id=42))

        assert "create_server_group" not in server.tools
        assert "update_server_group" not in server.tools
        assert "delete_server_group" not in server.tools
        assert "list_server_groups" in server.tools
        assert "get_server_group" in server.tools


# ---------------------------------------------------------------------------
# audit_tools
# ---------------------------------------------------------------------------


class TestAuditToolsDispatch:
    @pytest.mark.asyncio
    async def test_audit_trail_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake_audit(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(audit_tools.workflows, "audit_trail_user_activity", fake_audit)

        server = StubServer()
        audit_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["audit_trail_user_activity"](
            date="2026-01-15", actor_email="alice@example.com"
        )

        assert recorded.get("actor_email") == "alice@example.com"

    @pytest.mark.asyncio
    async def test_audit_trail_passes_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from datetime import date

        recorded: dict[str, Any] = {}

        async def fake_audit(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(audit_tools.workflows, "audit_trail_user_activity", fake_audit)

        server = StubServer()
        audit_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["audit_trail_user_activity"](date="2026-03-01")

        assert recorded.get("date") == date(2026, 3, 1)


# ---------------------------------------------------------------------------
# device_tools
# ---------------------------------------------------------------------------


class TestDeviceToolsDispatch:
    @pytest.mark.asyncio
    async def test_device_detail_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake_describe(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(device_tools.workflows, "describe_device", fake_describe)

        server = StubServer()
        device_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["device_detail"](device_id=101)

        assert recorded.get("device_id") == 101

    @pytest.mark.asyncio
    async def test_search_devices_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake_search(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(device_tools.workflows, "search_devices", fake_search)

        server = StubServer()
        device_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["search_devices"](hostname_contains="web-01")

        assert recorded.get("hostname_contains") == "web-01"

    @pytest.mark.asyncio
    async def test_device_health_metrics_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: list[bool] = []

        async def fake_health(client, **kwargs):
            called.append(True)
            return _success()

        monkeypatch.setattr(device_tools.workflows, "summarize_device_health", fake_health)

        server = StubServer()
        device_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["device_health_metrics"](group_id=5)

        assert called

    @pytest.mark.asyncio
    async def test_execute_device_command_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake_command(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(device_tools.workflows, "issue_device_command", fake_command)

        server = StubServer()
        device_tools.register(server, read_only=False, client=FakeClient(org_id=42))

        await server.tools["execute_device_command"](device_id=55, command_type="scan")

        assert recorded.get("device_id") == 55
        assert recorded.get("command_type") == "scan"

    @pytest.mark.asyncio
    async def test_get_device_inventory_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake_inventory(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(device_tools.workflows, "get_device_inventory", fake_inventory)

        server = StubServer()
        device_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["get_device_inventory"](device_id=77, category="Hardware")

        assert recorded.get("device_id") == 77
        assert recorded.get("category") == "Hardware"

    @pytest.mark.asyncio
    async def test_get_device_inventory_categories_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake_categories(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(
            device_tools.workflows, "get_device_inventory_categories", fake_categories
        )

        server = StubServer()
        device_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["get_device_inventory_categories"](device_id=88)

        assert recorded.get("device_id") == 88

    @pytest.mark.asyncio
    async def test_execute_device_command_absent_in_read_only(self) -> None:
        server = StubServer()
        device_tools.register(server, read_only=True, client=FakeClient(org_id=42))

        assert "execute_device_command" not in server.tools
        assert "device_detail" in server.tools
        assert "search_devices" in server.tools


# ---------------------------------------------------------------------------
# webhook_tools
# ---------------------------------------------------------------------------


class TestWebhookToolsDispatch:
    """Webhook tools use resolve_org_uuid internally.

    To avoid real HTTP calls, FakeClient is constructed with org_uuid already
    set so resolve_org_uuid returns it from the cache without hitting /orgs.
    """

    @pytest.mark.asyncio
    async def test_list_webhooks_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake_list(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(webhook_tools.workflows, "list_webhooks", fake_list)

        org_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        server = StubServer()
        webhook_tools.register(server, client=FakeClient(org_uuid=org_uuid))

        await server.tools["list_webhooks"](org_uuid=org_uuid)

        assert str(recorded.get("org_uuid")) == org_uuid

    @pytest.mark.asyncio
    async def test_create_webhook_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake_create(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(webhook_tools.workflows, "create_webhook", fake_create)

        org_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        server = StubServer()
        webhook_tools.register(server, read_only=False, client=FakeClient(org_uuid=org_uuid))

        await server.tools["create_webhook"](
            name="My Hook",
            url="https://example.com/hook",
            event_types=["device.compliant"],
            org_uuid=org_uuid,
        )

        assert recorded.get("name") == "My Hook"
        assert recorded.get("url") == "https://example.com/hook"
        assert recorded.get("event_types") == ["device.compliant"]

    @pytest.mark.asyncio
    async def test_test_webhook_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake_test(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(webhook_tools.workflows, "test_webhook", fake_test)

        org_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        wh_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        server = StubServer()
        webhook_tools.register(server, read_only=False, client=FakeClient(org_uuid=org_uuid))

        await server.tools["test_webhook"](webhook_id=wh_id, org_uuid=org_uuid)

        assert str(recorded.get("webhook_id")) == wh_id

    @pytest.mark.asyncio
    async def test_rotate_webhook_secret_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake_rotate(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(webhook_tools.workflows, "rotate_webhook_secret", fake_rotate)

        org_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        wh_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
        server = StubServer()
        webhook_tools.register(server, read_only=False, client=FakeClient(org_uuid=org_uuid))

        await server.tools["rotate_webhook_secret"](webhook_id=wh_id, org_uuid=org_uuid)

        assert str(recorded.get("webhook_id")) == wh_id

    @pytest.mark.asyncio
    async def test_write_webhooks_absent_in_read_only(self) -> None:
        server = StubServer()
        webhook_tools.register(server, read_only=True, client=FakeClient())

        assert "create_webhook" not in server.tools
        assert "test_webhook" not in server.tools
        assert "rotate_webhook_secret" not in server.tools
        assert "list_webhooks" in server.tools


# ---------------------------------------------------------------------------
# event_tools — error handling and response formatting
# ---------------------------------------------------------------------------


class TestEventToolsErrorHandling:
    @pytest.mark.asyncio
    async def test_list_events_response_contains_data_and_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_list_events(client, **kwargs):
            return {"data": {"events": [{"id": 1}]}, "metadata": {"total_count": 1}}

        monkeypatch.setattr(event_tools.workflows, "list_events", fake_list_events)

        server = StubServer()
        event_tools.register(server, client=FakeClient(org_id=42))

        result = await server.tools["list_events"](limit=10)

        assert "data" in result
        assert "metadata" in result

    @pytest.mark.asyncio
    async def test_list_events_raises_tool_error_on_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        server = StubServer()
        event_tools.register(server, client=FakeClient(org_id=42))

        # limit must be >= 1; passing 0 triggers a ValidationError
        with pytest.raises(ToolError):
            await server.tools["list_events"](limit=0)

    @pytest.mark.asyncio
    async def test_list_events_raises_tool_error_on_api_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.client import AutomoxAPIError

        async def fake_list_events(client, **kwargs):
            raise AutomoxAPIError("API failed", status_code=500, payload={})

        monkeypatch.setattr(event_tools.workflows, "list_events", fake_list_events)

        server = StubServer()
        event_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["list_events"]()

    @pytest.mark.asyncio
    async def test_list_events_raises_tool_error_on_rate_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.utils.tooling import RateLimitError

        async def fake_enforce():
            raise RateLimitError("rate limited")

        monkeypatch.setattr(_utils_tooling, "enforce_rate_limit", fake_enforce)

        server = StubServer()
        event_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["list_events"]()

    @pytest.mark.asyncio
    async def test_list_events_raises_tool_error_on_unexpected_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        async def fake_list_events(client, **kwargs):
            raise RuntimeError("unexpected boom")

        monkeypatch.setattr(event_tools.workflows, "list_events", fake_list_events)

        server = StubServer()
        event_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError, match="internal error occurred"):
            await server.tools["list_events"]()

    @pytest.mark.asyncio
    async def test_list_events_no_org_id_raises_tool_error(self) -> None:
        """inject_org_id=True with org_id=None must raise ToolError."""
        from fastmcp.exceptions import ToolError

        server = StubServer()
        event_tools.register(server, client=FakeClient(org_id=None))

        with pytest.raises(ToolError):
            await server.tools["list_events"]()


# ---------------------------------------------------------------------------
# report_tools — error handling and response formatting
# ---------------------------------------------------------------------------


class TestReportToolsErrorHandling:
    @pytest.mark.asyncio
    async def test_prepatch_report_response_contains_data_and_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_prepatch(client, **kwargs):
            return {"data": {"devices": []}, "metadata": {"total_count": 0}}

        monkeypatch.setattr(report_tools.workflows, "get_prepatch_report", fake_prepatch)

        server = StubServer()
        report_tools.register(server, client=FakeClient(org_id=42))

        result = await server.tools["prepatch_report"]()

        assert "data" in result
        assert "metadata" in result

    @pytest.mark.asyncio
    async def test_noncompliant_report_response_contains_data_and_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_noncompliant(client, **kwargs):
            return {"data": {"devices": [{"id": 99}]}, "metadata": {"total_count": 1}}

        monkeypatch.setattr(report_tools.workflows, "get_noncompliant_report", fake_noncompliant)

        server = StubServer()
        report_tools.register(server, client=FakeClient(org_id=42))

        result = await server.tools["noncompliant_report"]()

        assert "data" in result
        assert "metadata" in result

    @pytest.mark.asyncio
    async def test_prepatch_report_raises_tool_error_on_api_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.client import AutomoxAPIError

        async def fake_prepatch(client, **kwargs):
            raise AutomoxAPIError("Bad gateway", status_code=502, payload={})

        monkeypatch.setattr(report_tools.workflows, "get_prepatch_report", fake_prepatch)

        server = StubServer()
        report_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["prepatch_report"]()

    @pytest.mark.asyncio
    async def test_prepatch_report_raises_tool_error_on_rate_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.utils.tooling import RateLimitError

        async def fake_enforce():
            raise RateLimitError("rate limited")

        monkeypatch.setattr(_utils_tooling, "enforce_rate_limit", fake_enforce)

        server = StubServer()
        report_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["prepatch_report"]()

    @pytest.mark.asyncio
    async def test_prepatch_report_raises_tool_error_on_unexpected_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        async def fake_prepatch(client, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(report_tools.workflows, "get_prepatch_report", fake_prepatch)

        server = StubServer()
        report_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError, match="internal error occurred"):
            await server.tools["prepatch_report"]()

    @pytest.mark.asyncio
    async def test_noncompliant_report_no_org_id_raises_tool_error(self) -> None:
        """inject_org_id=True with org_id=None must raise ToolError."""
        from fastmcp.exceptions import ToolError

        server = StubServer()
        report_tools.register(server, client=FakeClient(org_id=None))

        with pytest.raises(ToolError):
            await server.tools["noncompliant_report"]()


# ---------------------------------------------------------------------------
# tools/__init__.py — register_tools module filtering
# ---------------------------------------------------------------------------


class TestRegisterToolsFiltering:
    def test_all_modules_registered_by_default(self) -> None:
        from automox_mcp.tools import register_tools

        server = StubServer()
        register_tools(server, client=FakeClient(org_id=42))

        # A sample tool from several different modules should be present
        assert "list_events" in server.tools
        assert "prepatch_report" in server.tools
        assert "list_server_groups" in server.tools

    def test_module_filtering_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import automox_mcp.tools as tools_mod
        from automox_mcp.tools import register_tools

        monkeypatch.setattr(tools_mod, "get_enabled_modules", lambda: {"events"})

        server = StubServer()
        register_tools(server, client=FakeClient(org_id=42))

        assert "list_events" in server.tools
        # report_tools and group_tools not enabled
        assert "prepatch_report" not in server.tools
        assert "list_server_groups" not in server.tools

    def test_import_error_is_skipped_gracefully(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import importlib

        from automox_mcp.tools import register_tools

        original_import = importlib.import_module

        def failing_import(name, package=None):
            if name.endswith("event_tools"):
                raise ImportError("simulated missing module")
            return original_import(name, package)

        monkeypatch.setattr(importlib, "import_module", failing_import)

        server = StubServer()
        # Should not raise; simply skip the failing module
        register_tools(server, client=FakeClient(org_id=42))
        assert "list_events" not in server.tools

    def test_register_exception_is_logged_not_raised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import importlib

        from automox_mcp.tools import register_tools

        original_import = importlib.import_module

        class _BrokenMod:
            def register(self, server, *, read_only=False, client):
                raise RuntimeError("registration exploded")

        def patched_import(name, package=None):
            if name.endswith("event_tools"):
                return _BrokenMod()
            return original_import(name, package)

        monkeypatch.setattr(importlib, "import_module", patched_import)

        server = StubServer()
        # Should not raise
        register_tools(server, client=FakeClient(org_id=42))


# ---------------------------------------------------------------------------
# audit_tools — error handling paths
# ---------------------------------------------------------------------------


class TestAuditToolsErrorHandling:
    @pytest.mark.asyncio
    async def test_audit_trail_raises_tool_error_on_api_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.client import AutomoxAPIError

        async def fake_audit(client, **kwargs):
            raise AutomoxAPIError("Forbidden", status_code=403, payload={})

        monkeypatch.setattr(audit_tools.workflows, "audit_trail_user_activity", fake_audit)

        server = StubServer()
        audit_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["audit_trail_user_activity"](date="2026-01-01")

    @pytest.mark.asyncio
    async def test_audit_trail_raises_tool_error_on_rate_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.utils.tooling import RateLimitError

        async def fake_enforce():
            raise RateLimitError("rate limited")

        monkeypatch.setattr(_utils_tooling, "enforce_rate_limit", fake_enforce)

        server = StubServer()
        audit_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["audit_trail_user_activity"](date="2026-01-01")

    @pytest.mark.asyncio
    async def test_audit_trail_raises_tool_error_on_unexpected_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        async def fake_audit(client, **kwargs):
            raise ValueError("something went wrong")

        monkeypatch.setattr(audit_tools.workflows, "audit_trail_user_activity", fake_audit)

        server = StubServer()
        audit_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["audit_trail_user_activity"](date="2026-01-01")

    @pytest.mark.asyncio
    async def test_audit_trail_response_has_data_and_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_audit(client, **kwargs):
            return {"data": {"events": []}, "metadata": {"total_count": 0}}

        monkeypatch.setattr(audit_tools.workflows, "audit_trail_user_activity", fake_audit)

        server = StubServer()
        audit_tools.register(server, client=FakeClient(org_id=42))

        result = await server.tools["audit_trail_user_activity"](date="2026-01-01")

        assert "data" in result
        assert "metadata" in result

    @pytest.mark.asyncio
    async def test_audit_trail_no_org_id_raises_tool_error(self) -> None:
        """OrgIdContextMixin with org_id=None must raise ToolError."""
        from fastmcp.exceptions import ToolError

        server = StubServer()
        audit_tools.register(server, client=FakeClient(org_id=None))

        with pytest.raises(ToolError):
            await server.tools["audit_trail_user_activity"](date="2026-01-01")


# ---------------------------------------------------------------------------
# compound_tools — error handling paths
# ---------------------------------------------------------------------------


class TestCompoundToolsErrorHandling:
    @pytest.mark.asyncio
    async def test_compliance_snapshot_raises_tool_error_on_api_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.client import AutomoxAPIError
        from automox_mcp.tools import compound_tools

        async def fake_snapshot(client, **kwargs):
            raise AutomoxAPIError("Server error", status_code=500, payload={})

        monkeypatch.setattr(
            compound_tools.workflows.compound, "get_compliance_snapshot", fake_snapshot
        )

        server = StubServer()
        compound_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["get_compliance_snapshot"]()

    @pytest.mark.asyncio
    async def test_compliance_snapshot_raises_tool_error_on_rate_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.tools import compound_tools
        from automox_mcp.utils.tooling import RateLimitError

        async def fake_enforce():
            raise RateLimitError("rate limited")

        monkeypatch.setattr(_utils_tooling, "enforce_rate_limit", fake_enforce)

        server = StubServer()
        compound_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["get_compliance_snapshot"]()

    @pytest.mark.asyncio
    async def test_compliance_snapshot_raises_tool_error_on_unexpected_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.tools import compound_tools

        async def fake_snapshot(client, **kwargs):
            raise ConnectionError("network down")

        monkeypatch.setattr(
            compound_tools.workflows.compound, "get_compliance_snapshot", fake_snapshot
        )

        server = StubServer()
        compound_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError, match="internal error occurred"):
            await server.tools["get_compliance_snapshot"]()

    @pytest.mark.asyncio
    async def test_compliance_snapshot_no_org_id_raises_tool_error(self) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.tools import compound_tools

        server = StubServer()
        compound_tools.register(server, client=FakeClient(org_id=None))

        with pytest.raises(ToolError):
            await server.tools["get_compliance_snapshot"]()

    @pytest.mark.asyncio
    async def test_compliance_snapshot_response_has_data_and_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from automox_mcp.tools import compound_tools

        async def fake_snapshot(client, **kwargs):
            return {"data": {"summary": {}}, "metadata": {}}

        monkeypatch.setattr(
            compound_tools.workflows.compound, "get_compliance_snapshot", fake_snapshot
        )

        server = StubServer()
        compound_tools.register(server, client=FakeClient(org_id=42))

        result = await server.tools["get_compliance_snapshot"]()

        assert "data" in result
        assert "metadata" in result


# ---------------------------------------------------------------------------
# package_tools — error handling paths
# ---------------------------------------------------------------------------


class TestPackageToolsErrorHandling:
    @pytest.mark.asyncio
    async def test_list_device_packages_raises_tool_error_on_api_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.client import AutomoxAPIError

        async def fake_list_pkgs(client, **kwargs):
            raise AutomoxAPIError("Not found", status_code=404, payload={})

        monkeypatch.setattr(package_tools.workflows, "list_device_packages", fake_list_pkgs)

        server = StubServer()
        package_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["list_device_packages"](device_id=7)

    @pytest.mark.asyncio
    async def test_list_device_packages_raises_tool_error_on_rate_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.utils.tooling import RateLimitError

        async def fake_enforce():
            raise RateLimitError("rate limited")

        monkeypatch.setattr(_utils_tooling, "enforce_rate_limit", fake_enforce)

        server = StubServer()
        package_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["list_device_packages"](device_id=7)

    @pytest.mark.asyncio
    async def test_list_device_packages_raises_tool_error_on_unexpected_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        async def fake_list_pkgs(client, **kwargs):
            raise TimeoutError("timed out")

        monkeypatch.setattr(package_tools.workflows, "list_device_packages", fake_list_pkgs)

        server = StubServer()
        package_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError, match="internal error occurred"):
            await server.tools["list_device_packages"](device_id=7)

    @pytest.mark.asyncio
    async def test_list_device_packages_no_org_id_raises_tool_error(self) -> None:
        """inject_org_id=True with org_id=None must raise ToolError."""
        from fastmcp.exceptions import ToolError

        server = StubServer()
        package_tools.register(server, client=FakeClient(org_id=None))

        with pytest.raises(ToolError):
            await server.tools["list_device_packages"](device_id=7)


# ---------------------------------------------------------------------------
# group_tools — error handling paths
# ---------------------------------------------------------------------------


class TestGroupToolsErrorHandling:
    @pytest.mark.asyncio
    async def test_list_server_groups_raises_tool_error_on_api_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.client import AutomoxAPIError

        async def fake_list(client, **kwargs):
            raise AutomoxAPIError("Server error", status_code=500, payload={})

        monkeypatch.setattr(group_tools.workflows, "list_server_groups", fake_list)

        server = StubServer()
        group_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["list_server_groups"]()

    @pytest.mark.asyncio
    async def test_list_server_groups_raises_tool_error_on_rate_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.utils.tooling import RateLimitError

        async def fake_enforce():
            raise RateLimitError("rate limited")

        monkeypatch.setattr(_utils_tooling, "enforce_rate_limit", fake_enforce)

        server = StubServer()
        group_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["list_server_groups"]()

    @pytest.mark.asyncio
    async def test_list_server_groups_raises_tool_error_on_unexpected_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        async def fake_list(client, **kwargs):
            raise MemoryError("out of memory")

        monkeypatch.setattr(group_tools.workflows, "list_server_groups", fake_list)

        server = StubServer()
        group_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError, match="internal error occurred"):
            await server.tools["list_server_groups"]()

    @pytest.mark.asyncio
    async def test_delete_server_group_mixin_org_id_injected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DeleteServerGroupParams uses OrgIdRequiredMixin — exercises the mixin branch."""
        recorded: dict[str, Any] = {}

        async def fake_delete(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(group_tools.workflows, "delete_server_group", fake_delete)

        server = StubServer()
        group_tools.register(server, read_only=False, client=FakeClient(org_id=42))

        await server.tools["delete_server_group"](group_id=10)

        assert recorded.get("group_id") == 10
        assert recorded.get("org_id") == 42

    @pytest.mark.asyncio
    async def test_delete_server_group_no_org_id_raises_tool_error(self) -> None:
        """OrgIdRequiredMixin with org_id=None must raise ToolError."""
        from fastmcp.exceptions import ToolError

        server = StubServer()
        group_tools.register(server, read_only=False, client=FakeClient(org_id=None))

        with pytest.raises(ToolError):
            await server.tools["delete_server_group"](group_id=10)


# ---------------------------------------------------------------------------
# device_tools — error handling paths
# ---------------------------------------------------------------------------


class TestDeviceToolsErrorHandling:
    @pytest.mark.asyncio
    async def test_device_detail_raises_tool_error_on_api_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.client import AutomoxAPIError

        async def fake_describe(client, **kwargs):
            raise AutomoxAPIError("Not found", status_code=404, payload={})

        monkeypatch.setattr(device_tools.workflows, "describe_device", fake_describe)

        server = StubServer()
        device_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["device_detail"](device_id=101)

    @pytest.mark.asyncio
    async def test_device_detail_raises_tool_error_on_rate_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.utils.tooling import RateLimitError

        async def fake_enforce():
            raise RateLimitError("rate limited")

        monkeypatch.setattr(_utils_tooling, "enforce_rate_limit", fake_enforce)

        server = StubServer()
        device_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["device_detail"](device_id=101)

    @pytest.mark.asyncio
    async def test_device_detail_raises_tool_error_on_unexpected_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        async def fake_describe(client, **kwargs):
            raise AttributeError("missing attr")

        monkeypatch.setattr(device_tools.workflows, "describe_device", fake_describe)

        server = StubServer()
        device_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError, match="internal error occurred"):
            await server.tools["device_detail"](device_id=101)

    @pytest.mark.asyncio
    async def test_devices_needing_attention_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake_list(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(device_tools.workflows, "list_devices_needing_attention", fake_list)

        server = StubServer()
        device_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["devices_needing_attention"](limit=5)

        assert recorded.get("limit") == 5


# ---------------------------------------------------------------------------
# account_tools — error handling paths
# ---------------------------------------------------------------------------


class TestAccountToolsErrorHandling:
    @pytest.mark.asyncio
    async def test_invite_user_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from automox_mcp.tools import account_tools

        recorded: dict[str, Any] = {}

        async def fake_invite(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(account_tools.workflows, "invite_user_to_account", fake_invite)
        monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "cccccccc-cccc-cccc-cccc-cccccccccccc")

        server = StubServer()
        account_tools.register(server, read_only=False, client=FakeClient(org_id=42))

        await server.tools["invite_user_to_account"](
            email="test@example.com", account_rbac_role="global-admin"
        )

        assert recorded.get("email") == "test@example.com"

    @pytest.mark.asyncio
    async def test_invite_user_raises_tool_error_on_api_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.client import AutomoxAPIError
        from automox_mcp.tools import account_tools

        async def fake_invite(client, **kwargs):
            raise AutomoxAPIError("Forbidden", status_code=403, payload={})

        monkeypatch.setattr(account_tools.workflows, "invite_user_to_account", fake_invite)
        monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "cccccccc-cccc-cccc-cccc-cccccccccccc")

        server = StubServer()
        account_tools.register(server, read_only=False, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["invite_user_to_account"](
                email="test@example.com", account_rbac_role="global-admin"
            )

    @pytest.mark.asyncio
    async def test_invite_user_raises_tool_error_on_rate_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.tools import account_tools
        from automox_mcp.utils.tooling import RateLimitError

        async def fake_enforce():
            raise RateLimitError("rate limited")

        monkeypatch.setattr(_utils_tooling, "enforce_rate_limit", fake_enforce)
        monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "cccccccc-cccc-cccc-cccc-cccccccccccc")

        server = StubServer()
        account_tools.register(server, read_only=False, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["invite_user_to_account"](
                email="test@example.com", account_rbac_role="global-admin"
            )

    @pytest.mark.asyncio
    async def test_invite_user_raises_tool_error_on_unexpected_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.tools import account_tools

        async def fake_invite(client, **kwargs):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(account_tools.workflows, "invite_user_to_account", fake_invite)
        monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "cccccccc-cccc-cccc-cccc-cccccccccccc")

        server = StubServer()
        account_tools.register(server, read_only=False, client=FakeClient(org_id=42))

        with pytest.raises(ToolError, match="internal error occurred"):
            await server.tools["invite_user_to_account"](
                email="test@example.com", account_rbac_role="global-admin"
            )

    @pytest.mark.asyncio
    async def test_account_tools_absent_in_read_only(self) -> None:
        from automox_mcp.tools import account_tools

        server = StubServer()
        account_tools.register(server, read_only=True, client=FakeClient(org_id=42))

        assert "invite_user_to_account" not in server.tools
        assert "remove_user_from_account" not in server.tools

    @pytest.mark.asyncio
    async def test_missing_account_uuid_raises_tool_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.tools import account_tools

        async def fake_invite(client, **kwargs):
            return _success()

        monkeypatch.setattr(account_tools.workflows, "invite_user_to_account", fake_invite)
        monkeypatch.delenv("AUTOMOX_ACCOUNT_UUID", raising=False)

        server = StubServer()
        account_tools.register(server, read_only=False, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["invite_user_to_account"](
                email="test@example.com", account_rbac_role="global-admin"
            )


# ---------------------------------------------------------------------------
# compound_tools — _call_with_org_uuid error paths
# ---------------------------------------------------------------------------


class TestCompoundToolsOrgUuidErrorHandling:
    @pytest.mark.asyncio
    async def test_patch_tuesday_raises_tool_error_on_api_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.client import AutomoxAPIError
        from automox_mcp.tools import compound_tools

        async def fake_readiness(client, **kwargs):
            raise AutomoxAPIError("Server error", status_code=500, payload={})

        async def fake_resolve(
            client, *, explicit_uuid=None, org_id=None, allow_account_uuid=False
        ):
            return "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        monkeypatch.setattr(
            compound_tools.workflows.compound,
            "get_patch_tuesday_readiness",
            fake_readiness,
        )
        monkeypatch.setattr("automox_mcp.utils.organization.resolve_org_uuid", fake_resolve)

        server = StubServer()
        compound_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["get_patch_tuesday_readiness"]()

    @pytest.mark.asyncio
    async def test_patch_tuesday_raises_tool_error_on_rate_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.tools import compound_tools
        from automox_mcp.utils.tooling import RateLimitError

        async def fake_enforce():
            raise RateLimitError("rate limited")

        monkeypatch.setattr(_utils_tooling, "enforce_rate_limit", fake_enforce)

        server = StubServer()
        compound_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError):
            await server.tools["get_patch_tuesday_readiness"]()

    @pytest.mark.asyncio
    async def test_patch_tuesday_raises_tool_error_on_unexpected_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.tools import compound_tools

        async def fake_readiness(client, **kwargs):
            raise KeyError("missing key")

        async def fake_resolve(
            client, *, explicit_uuid=None, org_id=None, allow_account_uuid=False
        ):
            return "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

        monkeypatch.setattr(
            compound_tools.workflows.compound,
            "get_patch_tuesday_readiness",
            fake_readiness,
        )
        monkeypatch.setattr("automox_mcp.utils.organization.resolve_org_uuid", fake_resolve)

        server = StubServer()
        compound_tools.register(server, client=FakeClient(org_id=42))

        with pytest.raises(ToolError, match="internal error occurred"):
            await server.tools["get_patch_tuesday_readiness"]()

    @pytest.mark.asyncio
    async def test_get_device_full_profile_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from automox_mcp.tools import compound_tools

        recorded: dict[str, Any] = {}

        async def fake_profile(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(
            compound_tools.workflows.compound, "get_device_full_profile", fake_profile
        )

        server = StubServer()
        compound_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["get_device_full_profile"](device_id=55)

        assert recorded.get("device_id") == 55


# ---------------------------------------------------------------------------
# policy_tools — error handling paths
# ---------------------------------------------------------------------------


class TestPolicyToolsErrorHandling:
    @pytest.mark.asyncio
    async def test_policy_health_overview_raises_tool_error_on_api_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.client import AutomoxAPIError
        from automox_mcp.tools import policy_tools

        async def fake_activity(client, **kwargs):
            raise AutomoxAPIError("Server error", status_code=500, payload={})

        monkeypatch.setattr(policy_tools.workflows, "summarize_policy_activity", fake_activity)

        org_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        server = StubServer()
        policy_tools.register(server, client=FakeClient(org_uuid=org_uuid))

        with pytest.raises(ToolError):
            await server.tools["policy_health_overview"](org_uuid=org_uuid)

    @pytest.mark.asyncio
    async def test_policy_health_overview_raises_tool_error_on_rate_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.tools import policy_tools
        from automox_mcp.utils.tooling import RateLimitError

        async def fake_enforce():
            raise RateLimitError("rate limited")

        monkeypatch.setattr(_utils_tooling, "enforce_rate_limit", fake_enforce)

        org_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        server = StubServer()
        policy_tools.register(server, client=FakeClient(org_uuid=org_uuid))

        with pytest.raises(ToolError):
            await server.tools["policy_health_overview"](org_uuid=org_uuid)

    @pytest.mark.asyncio
    async def test_policy_health_overview_raises_tool_error_on_unexpected_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.tools import policy_tools

        async def fake_activity(client, **kwargs):
            raise TypeError("unexpected")

        monkeypatch.setattr(policy_tools.workflows, "summarize_policy_activity", fake_activity)

        org_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        server = StubServer()
        policy_tools.register(server, client=FakeClient(org_uuid=org_uuid))

        with pytest.raises(ToolError, match="internal error occurred"):
            await server.tools["policy_health_overview"](org_uuid=org_uuid)

    @pytest.mark.asyncio
    async def test_policy_catalog_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from automox_mcp.tools import policy_tools

        called: list[bool] = []

        async def fake_catalog(client, **kwargs):
            called.append(True)
            return _success()

        monkeypatch.setattr(policy_tools.workflows, "summarize_policies", fake_catalog)

        server = StubServer()
        policy_tools.register(server, client=FakeClient(org_id=42))

        await server.tools["policy_catalog"](limit=10, page=0)

        assert called

    @pytest.mark.asyncio
    async def test_policy_detail_raises_tool_error_on_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastmcp.exceptions import ToolError

        from automox_mcp.tools import policy_tools

        server = StubServer()
        policy_tools.register(server, client=FakeClient(org_id=42))

        # policy_id is required — omitting it should produce a ValidationError → ToolError
        with pytest.raises((ToolError, TypeError)):
            await server.tools["policy_detail"]()

    @pytest.mark.asyncio
    async def test_write_policy_tools_absent_in_read_only(self) -> None:
        from automox_mcp.tools import policy_tools

        server = StubServer()
        policy_tools.register(server, read_only=True, client=FakeClient(org_id=42))

        assert "decide_patch_approval" not in server.tools
        assert "delete_policy" not in server.tools
        assert "policy_catalog" in server.tools
        assert "policy_health_overview" in server.tools


# ---------------------------------------------------------------------------
# splashtop_tools
# ---------------------------------------------------------------------------


_DEV_UUID = "550e8400-e29b-41d4-a716-446655440000"


class TestSplashtopToolsDispatch:
    @pytest.mark.asyncio
    async def test_device_status_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(splashtop_tools, "_get_device_status", fake)

        server = StubServer()
        splashtop_tools.register(server, client=FakeClient())

        await server.tools["splashtop_device_status"](device_uuid=_DEV_UUID)
        assert str(recorded.get("device_uuid")) == _DEV_UUID

    @pytest.mark.asyncio
    async def test_session_status_passes_account_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(splashtop_tools, "_get_session_status", fake)

        server = StubServer()
        splashtop_tools.register(server, client=FakeClient())

        await server.tools["splashtop_session_status"](
            device_uuid=_DEV_UUID, account_type="PREMIUM"
        )
        assert str(recorded.get("device_uuid")) == _DEV_UUID
        assert recorded.get("account_type") == "PREMIUM"

    @pytest.mark.asyncio
    async def test_get_attended_access_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(splashtop_tools, "_get_attended_access", fake)

        server = StubServer()
        splashtop_tools.register(server, client=FakeClient())

        await server.tools["splashtop_get_attended_access"](device_uuid=_DEV_UUID)
        assert str(recorded.get("device_uuid")) == _DEV_UUID

    @pytest.mark.asyncio
    async def test_install_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(splashtop_tools, "_install_splashtop", fake)

        server = StubServer()
        splashtop_tools.register(server, read_only=False, client=FakeClient())

        await server.tools["splashtop_install"](
            device_uuid=_DEV_UUID,
            os_family="windows",
            request_permission="not_needed",
            organization_uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            account_type="BASIC",
        )
        assert str(recorded.get("device_uuid")) == _DEV_UUID
        assert recorded.get("os_family") == "windows"
        assert recorded.get("request_permission") == "not_needed"

    @pytest.mark.asyncio
    async def test_bulk_install_uninstall_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(splashtop_tools, "_bulk_install_uninstall", fake)

        server = StubServer()
        splashtop_tools.register(server, read_only=False, client=FakeClient())

        await server.tools["splashtop_bulk_install_uninstall"](
            action="uninstall", server_group_id=42
        )
        assert recorded.get("action") == "uninstall"
        assert recorded.get("server_group_id") == 42

    @pytest.mark.asyncio
    async def test_initiate_connection_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(splashtop_tools, "_initiate_connection", fake)

        server = StubServer()
        splashtop_tools.register(server, read_only=False, client=FakeClient())

        await server.tools["splashtop_initiate_connection"](
            device_uuid=_DEV_UUID,
            os_family="windows",
            connection_type="remote_control",
        )
        assert str(recorded.get("device_uuid")) == _DEV_UUID
        assert recorded.get("connection_type") == "remote_control"

    @pytest.mark.asyncio
    async def test_force_disconnect_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(splashtop_tools, "_force_disconnect", fake)

        server = StubServer()
        splashtop_tools.register(server, read_only=False, client=FakeClient())

        await server.tools["splashtop_force_disconnect"](device_uuid=_DEV_UUID, os_family="windows")
        assert str(recorded.get("device_uuid")) == _DEV_UUID

    @pytest.mark.asyncio
    async def test_set_attended_access_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(splashtop_tools, "_set_attended_access", fake)

        server = StubServer()
        splashtop_tools.register(server, read_only=False, client=FakeClient())

        await server.tools["splashtop_set_attended_access"](
            device_uuid=_DEV_UUID, required_attended_access=False
        )
        assert str(recorded.get("device_uuid")) == _DEV_UUID
        assert recorded.get("required_attended_access") is False

    @pytest.mark.asyncio
    async def test_set_bulk_attended_access_calls_workflow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(splashtop_tools, "_set_bulk_attended_access", fake)

        server = StubServer()
        splashtop_tools.register(server, read_only=False, client=FakeClient())

        await server.tools["splashtop_set_bulk_attended_access"](
            device_uuids=[_DEV_UUID], required_attended_access=True
        )
        assert [str(u) for u in recorded.get("device_uuids", [])] == [_DEV_UUID]
        assert recorded.get("required_attended_access") is True

    @pytest.mark.asyncio
    async def test_uninstall_calls_workflow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(splashtop_tools, "_uninstall_splashtop", fake)

        server = StubServer()
        splashtop_tools.register(server, read_only=False, client=FakeClient())

        await server.tools["splashtop_uninstall"](device_uuid=_DEV_UUID, os_family="windows")
        assert str(recorded.get("device_uuid")) == _DEV_UUID

    @pytest.mark.asyncio
    async def test_write_tools_absent_in_read_only(self) -> None:
        server = StubServer()
        splashtop_tools.register(server, read_only=True, client=FakeClient())

        for write_tool in (
            "splashtop_install",
            "splashtop_bulk_install_uninstall",
            "splashtop_initiate_connection",
            "splashtop_force_disconnect",
            "splashtop_set_attended_access",
            "splashtop_set_bulk_attended_access",
            "splashtop_uninstall",
        ):
            assert write_tool not in server.tools

        for read_tool in (
            "splashtop_device_status",
            "splashtop_session_status",
            "splashtop_get_attended_access",
        ):
            assert read_tool in server.tools


class TestSplashtopIdempotencyAndExceptionPaths:
    """Exercise the cache-hit + exception-release branches for all
    splashtop write tools to keep coverage of those handlers green."""

    _WRITE_CASES = [
        (
            "splashtop_install",
            "_install_splashtop",
            {"device_uuid": _DEV_UUID, "os_family": "windows"},
        ),
        (
            "splashtop_bulk_install_uninstall",
            "_bulk_install_uninstall",
            {"action": "install"},
        ),
        (
            "splashtop_initiate_connection",
            "_initiate_connection",
            {
                "device_uuid": _DEV_UUID,
                "os_family": "windows",
                "connection_type": "remote_control",
            },
        ),
        (
            "splashtop_force_disconnect",
            "_force_disconnect",
            {"device_uuid": _DEV_UUID, "os_family": "windows"},
        ),
        (
            "splashtop_set_attended_access",
            "_set_attended_access",
            {"device_uuid": _DEV_UUID, "required_attended_access": True},
        ),
        (
            "splashtop_set_bulk_attended_access",
            "_set_bulk_attended_access",
            {"device_uuids": [_DEV_UUID], "required_attended_access": True},
        ),
        (
            "splashtop_uninstall",
            "_uninstall_splashtop",
            {"device_uuid": _DEV_UUID, "os_family": "windows"},
        ),
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name,wf_attr,kwargs", _WRITE_CASES)
    async def test_cache_hit_short_circuits_workflow(
        self,
        tool_name: str,
        wf_attr: str,
        kwargs: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        called: list[bool] = []

        async def fake_check(request_id: str | None, name: str):
            return {"data": {"cached": True}, "metadata": {"deprecated_endpoint": False}}

        async def fake_wf(client, **_):
            called.append(True)
            return _success()

        monkeypatch.setattr(splashtop_tools, "check_idempotency", fake_check)
        monkeypatch.setattr(splashtop_tools, wf_attr, fake_wf)

        server = StubServer()
        splashtop_tools.register(server, read_only=False, client=FakeClient())

        result = await server.tools[tool_name](request_id="req-1", **kwargs)
        assert result == {"data": {"cached": True}, "metadata": {"deprecated_endpoint": False}}
        assert called == []  # workflow not invoked on cache hit

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name,wf_attr,kwargs", _WRITE_CASES)
    async def test_workflow_exception_releases_idempotency(
        self,
        tool_name: str,
        wf_attr: str,
        kwargs: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        released: list[str] = []

        async def fake_release(request_id: str | None, name: str):
            released.append(name)

        async def fake_wf(client, **_):
            raise RuntimeError("upstream blew up")

        monkeypatch.setattr(splashtop_tools, "release_idempotency", fake_release)
        monkeypatch.setattr(splashtop_tools, wf_attr, fake_wf)

        server = StubServer()
        splashtop_tools.register(server, read_only=False, client=FakeClient())

        from fastmcp.exceptions import ToolError

        with pytest.raises((RuntimeError, ToolError)):
            await server.tools[tool_name](request_id="req-2", **kwargs)

        assert released == [tool_name]


# ---------------------------------------------------------------------------
# account_tools — identity/zone/key writes (issue #91 category A, write slice)
# ---------------------------------------------------------------------------

_ACCT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class TestAccountWriteToolsDispatch:
    def _wire(self, monkeypatch: pytest.MonkeyPatch, name: str) -> dict[str, Any]:
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(account_tools.workflows, name, fake)
        return recorded

    @pytest.mark.asyncio
    async def test_list_user_api_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded = self._wire(monkeypatch, "list_user_api_keys")
        server = StubServer()
        account_tools.register(server, read_only=False, client=FakeClient(org_id=42))
        await server.tools["list_user_api_keys"](user_id=7)
        assert recorded["user_id"] == 7
        assert recorded["org_id"] == 42

    @pytest.mark.asyncio
    async def test_get_user_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded = self._wire(monkeypatch, "get_user_api_key")
        server = StubServer()
        account_tools.register(server, read_only=False, client=FakeClient(org_id=42))
        await server.tools["get_user_api_key"](user_id=7, key_id=3)
        assert recorded["key_id"] == 3

    @pytest.mark.asyncio
    async def test_create_zone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", _ACCT_UUID)
        recorded = self._wire(monkeypatch, "create_zone")
        server = StubServer()
        account_tools.register(server, read_only=False, client=FakeClient(org_id=42))
        await server.tools["create_zone"](name="EU Zone")
        assert recorded["name"] == "EU Zone"
        assert str(recorded["account_id"]) == _ACCT_UUID

    @pytest.mark.asyncio
    async def test_update_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded = self._wire(monkeypatch, "update_user")
        server = StubServer()
        account_tools.register(server, read_only=False, client=FakeClient(org_id=42))
        await server.tools["update_user"](user_id=7, email="a@b.c")
        assert recorded["user_id"] == 7
        assert recorded["email"] == "a@b.c"
        assert "password" not in recorded

    @pytest.mark.asyncio
    async def test_create_user_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded = self._wire(monkeypatch, "create_user_api_key")
        server = StubServer()
        account_tools.register(server, read_only=False, client=FakeClient(org_id=42))
        await server.tools["create_user_api_key"](user_id=7, name="k", expires_at="2027-01-01")
        assert recorded["name"] == "k"
        assert recorded["expires_at"] == "2027-01-01"

    @pytest.mark.asyncio
    async def test_update_user_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded = self._wire(monkeypatch, "update_user_api_key")
        server = StubServer()
        account_tools.register(server, read_only=False, client=FakeClient(org_id=42))
        await server.tools["update_user_api_key"](user_id=7, key_id=3, is_enabled=False)
        assert recorded["is_enabled"] is False

    @pytest.mark.asyncio
    async def test_delete_user_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded = self._wire(monkeypatch, "delete_user_api_key")
        server = StubServer()
        account_tools.register(server, read_only=False, client=FakeClient(org_id=42))
        await server.tools["delete_user_api_key"](user_id=7, key_id=3)
        assert recorded["key_id"] == 3

    @pytest.mark.asyncio
    async def test_write_tools_absent_in_read_only(self) -> None:
        server = StubServer()
        account_tools.register(server, read_only=True, client=FakeClient(org_id=42))
        for name in (
            "create_zone",
            "update_user",
            "create_user_api_key",
            "update_user_api_key",
            "delete_user_api_key",
        ):
            assert name not in server.tools


class TestAccountReadToolsDispatch:
    def _wire(self, monkeypatch: pytest.MonkeyPatch, name: str) -> dict[str, Any]:
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(account_tools.workflows, name, fake)
        return recorded

    @pytest.mark.asyncio
    async def test_list_organizations(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._wire(monkeypatch, "list_organizations")
        server = StubServer()
        account_tools.register(server, read_only=False, client=FakeClient(org_id=42))
        result = await server.tools["list_organizations"](page=1, limit=10)
        assert result["metadata"]["deprecated_endpoint"] is False

    @pytest.mark.asyncio
    async def test_list_users_and_get_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lu = self._wire(monkeypatch, "list_users")
        gu = self._wire(monkeypatch, "get_user")
        server = StubServer()
        account_tools.register(server, read_only=False, client=FakeClient(org_id=42))
        await server.tools["list_users"](limit=5)
        await server.tools["get_user"](user_id=7)
        assert lu["org_id"] == 42
        assert gu["user_id"] == 7

    @pytest.mark.asyncio
    async def test_account_scoped_reads(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", _ACCT_UUID)
        for name in (
            "get_account",
            "list_account_rbac_roles",
            "list_zones",
        ):
            self._wire(monkeypatch, name)
        uid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        zid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        for name in ("get_account_user", "list_zones_for_user"):
            self._wire(monkeypatch, name)
        for name in ("get_zone", "list_zone_users"):
            self._wire(monkeypatch, name)

        server = StubServer()
        account_tools.register(server, read_only=False, client=FakeClient(org_id=42))
        await server.tools["get_account"]()
        await server.tools["list_account_rbac_roles"]()
        await server.tools["list_zones"](page=0, limit=10)
        await server.tools["get_account_user"](user_id=uid)
        await server.tools["list_zones_for_user"](user_id=uid)
        await server.tools["get_zone"](zone_id=zid)
        await server.tools["list_zone_users"](zone_id=zid)
        # all dispatched without error
        assert "get_zone" in server.tools


class TestVulnSyncRemediationDispatch:
    @pytest.mark.asyncio
    async def test_apply_remediation_actions_dispatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTOMOX_MCP_ALLOW_REMEDIATION", "true")
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(vuln_sync_tools, "_apply_remediation_actions", fake)

        server = StubServer()
        vuln_sync_tools.register(server, read_only=False, client=FakeClient(org_id=42))
        await server.tools["apply_remediation_actions"](
            action_set_id=7,
            actions=[{"action": "patch-now", "solution_id": 5, "devices": [1, 2]}],
        )
        assert recorded["action_set_id"] == 7
        assert recorded["org_id"] == 42


class TestCategoryCAssessmentDispatch:
    @pytest.mark.asyncio
    async def test_preview_policy_device_filters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(policy_tools.workflows, "preview_policy_device_filters", fake)
        server = StubServer()
        policy_tools.register(server, read_only=False, client=FakeClient(org_id=42))
        await server.tools["preview_policy_device_filters"](
            device_filters=[{"field": "tag", "op": "in", "value": ["prod"]}],
            server_groups=[10],
        )
        assert recorded["server_groups"] == [10]
        assert recorded["org_id"] == 42

    @pytest.mark.asyncio
    async def test_list_devices_for_policies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(policy_tools.workflows, "list_devices_for_policies", fake)
        server = StubServer()
        policy_tools.register(server, read_only=False, client=FakeClient(org_id=42))
        pol = ["11111111-1111-1111-1111-111111111111"]
        await server.tools["list_devices_for_policies"](policies=pol)
        assert recorded["policies"] == pol

    @pytest.mark.asyncio
    async def test_batch_update_devices(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: dict[str, Any] = {}

        async def fake(client, **kwargs):
            recorded.update(kwargs)
            return _success()

        monkeypatch.setattr(device_tools.workflows, "batch_update_devices", fake)
        server = StubServer()
        device_tools.register(server, read_only=False, client=FakeClient(org_id=42))
        await server.tools["batch_update_devices"](
            devices=[1, 2],
            actions=[{"attribute": "tags", "action": "apply", "value": ["x"]}],
        )
        assert recorded["devices"] == [1, 2]

    @pytest.mark.asyncio
    async def test_batch_update_devices_absent_in_read_only(self) -> None:
        server = StubServer()
        device_tools.register(server, read_only=True, client=FakeClient(org_id=42))
        assert "batch_update_devices" not in server.tools

"""Tests for MCP resource registration and content."""

import pytest

from automox_mcp.resources.platform_resources import register as register_platform
from automox_mcp.resources.policy_resources import register_policy_resources


class StubServer:
    """Lightweight FastMCP stub that captures resource registrations."""

    def __init__(self) -> None:
        self.resources: dict[str, dict] = {}

    def resource(
        self, uri: str, *, name: str, description: str, mime_type: str = "application/json"
    ):
        def decorator(func):
            self.resources[uri] = {
                "name": name,
                "description": description,
                "mime_type": mime_type,
                "func": func,
            }
            return func

        return decorator


# ---------------------------------------------------------------------------
# Platform resource tests
# ---------------------------------------------------------------------------


class TestPlatformResources:
    """Tests for the four new platform reference resources."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.server = StubServer()
        register_platform(self.server)

    def test_filter_syntax_resource_registered(self) -> None:
        assert "resource://filters/syntax" in self.server.resources

    def test_filter_syntax_has_search_device_fields(self) -> None:
        func = self.server.resources["resource://filters/syntax"]["func"]
        data = func()
        assert "search_devices_filters" in data
        fields = data["search_devices_filters"]["fields"]
        assert "hostname_contains" in fields
        assert "ip_address" in fields
        assert "severity" in fields
        assert "managed" in fields

    def test_filter_syntax_has_policy_device_filters(self) -> None:
        func = self.server.resources["resource://filters/syntax"]["func"]
        data = func()
        assert "policy_device_filters" in data
        assert "example" in data["policy_device_filters"]

    def test_patch_categories_resource_registered(self) -> None:
        assert "resource://patches/categories" in self.server.resources

    def test_patch_categories_has_severity_levels(self) -> None:
        func = self.server.resources["resource://patches/categories"]["func"]
        data = func()
        assert "severity_levels" in data
        levels = data["severity_levels"]["levels"]
        severity_names = {level["name"] for level in levels}
        assert {"critical", "high", "medium", "low", "none", "unassigned"} == severity_names

    def test_patch_categories_has_patch_rules(self) -> None:
        func = self.server.resources["resource://patches/categories"]["func"]
        data = func()
        assert "patch_rules" in data
        options = data["patch_rules"]["options"]
        assert "all" in options
        assert "filter" in options
        assert "severity" in options

    def test_supported_os_resource_registered(self) -> None:
        assert "resource://platform/supported-os" in self.server.resources

    def test_supported_os_has_all_families(self) -> None:
        func = self.server.resources["resource://platform/supported-os"]["func"]
        data = func()
        families = data["os_families"]
        assert "Windows" in families
        assert "Mac" in families
        assert "Linux" in families

    def test_supported_os_windows_has_shell_types(self) -> None:
        func = self.server.resources["resource://platform/supported-os"]["func"]
        data = func()
        windows = data["os_families"]["Windows"]
        assert "PowerShell" in windows["shell_types"]
        assert windows["worklet_support"] is True

    def test_supported_os_linux_has_distributions(self) -> None:
        func = self.server.resources["resource://platform/supported-os"]["func"]
        data = func()
        linux = data["os_families"]["Linux"]
        assert "distributions" in linux
        assert len(linux["distributions"]) > 0

    def test_rate_limits_resource_registered(self) -> None:
        assert "resource://api/rate-limits" in self.server.resources

    def test_rate_limits_has_mcp_server_config(self) -> None:
        func = self.server.resources["resource://api/rate-limits"]["func"]
        data = func()
        mcp_limits = data["mcp_server_rate_limit"]
        assert mcp_limits["max_calls"] == 30
        assert mcp_limits["period_seconds"] == 60

    def test_rate_limits_has_efficiency_tips(self) -> None:
        func = self.server.resources["resource://api/rate-limits"]["func"]
        data = func()
        tips = data["tips_for_efficient_usage"]
        assert len(tips) > 0
        # Should mention compound tools
        assert any("compound" in tip.lower() for tip in tips)


# ---------------------------------------------------------------------------
# Existing resource tests (policy resources)
# ---------------------------------------------------------------------------


class TestPolicyResources:
    """Basic registration tests for policy resources."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.server = StubServer()
        register_policy_resources(self.server)

    def test_quick_start_registered(self) -> None:
        assert "resource://policies/quick-start" in self.server.resources

    def test_schema_registered(self) -> None:
        assert "resource://policies/schema" in self.server.resources

    def test_schedule_syntax_registered(self) -> None:
        assert "resource://policies/schedule-syntax" in self.server.resources

    def test_quick_start_has_templates(self) -> None:
        func = self.server.resources["resource://policies/quick-start"]["func"]
        data = func()
        assert "patch_policy_by_software_name" in data
        assert "patch_all_software" in data
        assert "critical_patches_only" in data

    def test_schema_has_policy_types(self) -> None:
        func = self.server.resources["resource://policies/schema"]["func"]
        data = func()
        assert "policy_types" in data
        types = data["policy_types"]
        assert "patch" in types
        assert "custom" in types
        assert "required_software" in types

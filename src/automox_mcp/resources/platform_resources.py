"""Platform reference resources for Automox MCP."""

from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP


def register(server: FastMCP) -> None:
    """Register platform reference resources."""

    @server.resource(
        "resource://filters/syntax",
        name="Device Filter Syntax",
        description=(
            "Reference for Automox device filtering syntax used in search_devices "
            "and policy device_filters. Includes field names, operators, and examples."
        ),
        mime_type="application/json",
    )
    def get_filter_syntax() -> dict[str, Any]:
        return {
            "search_devices_filters": {
                "description": (
                    "Parameters accepted by the search_devices tool for filtering devices"
                ),
                "fields": {
                    "hostname_contains": {
                        "type": "string",
                        "description": "Match devices whose hostname or custom name contains this text",
                        "example": "web-prod",
                    },
                    "ip_address": {
                        "type": "string",
                        "description": "Match devices with this IP address (exact match)",
                        "example": "10.0.1.50",
                    },
                    "tag": {
                        "type": "string",
                        "description": "Match devices containing this tag",
                        "example": "production",
                    },
                    "patch_status": {
                        "type": "string",
                        "values": ["missing"],
                        "description": "Filter by patch status. Only 'missing' is supported.",
                    },
                    "severity": {
                        "type": "string or list",
                        "values": ["critical", "high", "medium", "low", "none", "unassigned"],
                        "description": "Filter by severity of missing patches",
                        "examples": ['"critical"', '["critical", "high"]'],
                    },
                    "managed": {
                        "type": "boolean",
                        "description": "Filter by managed status (true/false)",
                    },
                    "group_id": {
                        "type": "integer",
                        "description": "Restrict results to a specific server group",
                    },
                },
            },
            "policy_device_filters": {
                "description": (
                    "Advanced device filter syntax used in policy device_filters field "
                    "to target specific devices beyond server group membership"
                ),
                "structure": [
                    {
                        "type": "group",
                        "server_group_id": "<integer>",
                        "description": "Target devices in a specific server group",
                    },
                    {
                        "type": "tag",
                        "tag_name": "<string>",
                        "description": "Target devices with a specific tag",
                    },
                ],
                "example": [
                    {"type": "group", "server_group_id": 12345},
                    {"type": "tag", "tag_name": "production"},
                ],
            },
            "list_devices_filters": {
                "description": "Query parameters accepted by the list_devices tool",
                "fields": {
                    "group_id": "Filter by Server Group ID",
                    "managed": "Filter by managed status (true/false)",
                    "patch_status": "Filter by patch status (e.g., 'missing')",
                    "limit": "Number of results per page (1-500)",
                    "page": "Page number (0-indexed)",
                },
            },
        }

    @server.resource(
        "resource://patches/categories",
        name="Patch Classification Categories",
        description=(
            "Mapping of Automox patch classification categories, severity levels, "
            "and patch_rule options used in policy configuration."
        ),
        mime_type="application/json",
    )
    def get_patch_categories() -> dict[str, Any]:
        return {
            "severity_levels": {
                "description": "Patch severity classifications used across the Automox platform",
                "levels": [
                    {
                        "name": "critical",
                        "description": "Highest severity — vulnerabilities actively exploited or trivially exploitable",
                    },
                    {
                        "name": "high",
                        "description": "Significant risk — should be patched within days",
                    },
                    {
                        "name": "medium",
                        "description": "Moderate risk — patch within standard maintenance windows",
                    },
                    {
                        "name": "low",
                        "description": "Minor risk — patch as part of regular maintenance",
                    },
                    {
                        "name": "none",
                        "description": "No severity assigned by the vendor",
                    },
                    {
                        "name": "unassigned",
                        "description": "Severity not yet classified",
                    },
                ],
            },
            "patch_rules": {
                "description": "Values for the configuration.patch_rule field in patch policies",
                "options": {
                    "all": "Patch all available software — no filtering",
                    "filter": "Patch specific software matching name patterns in configuration.filters",
                    "severity": "Patch only packages matching the severity in configuration.severity",
                    "custom": "Custom patch selection logic",
                },
            },
            "package_statuses": {
                "description": "Possible status values for software packages on a device",
                "statuses": {
                    "installed": "Package is installed and up to date",
                    "available": "A newer version is available but not yet installed",
                    "missing": "Package is required but not installed",
                    "pending": "Package installation is queued or in progress",
                },
            },
            "filter_pattern_syntax": {
                "description": "Wildcard patterns used in configuration.filters for patch policies",
                "syntax": "Use * as wildcard. Patterns are case-insensitive.",
                "examples": [
                    {"pattern": "*Google Chrome*", "matches": "Any package containing 'Google Chrome'"},
                    {"pattern": "*Firefox*", "matches": "Any package containing 'Firefox'"},
                    {"pattern": "Microsoft*", "matches": "Any package starting with 'Microsoft'"},
                ],
                "tip": (
                    "Use the filter_name shortcut in configuration to auto-wrap "
                    "a name with wildcards: filter_name='Chrome' becomes filters=['*Chrome*']"
                ),
            },
        }

    @server.resource(
        "resource://platform/supported-os",
        name="Supported Operating Systems",
        description=(
            "Matrix of operating systems supported by the Automox agent, "
            "including OS families and version details."
        ),
        mime_type="application/json",
    )
    def get_supported_os() -> dict[str, Any]:
        return {
            "os_families": {
                "Windows": {
                    "agent_supported": True,
                    "versions": [
                        "Windows 11 (23H2, 22H2)",
                        "Windows 10 (22H2, 21H2)",
                        "Windows Server 2022",
                        "Windows Server 2019",
                        "Windows Server 2016",
                        "Windows Server 2012 R2",
                    ],
                    "shell_types": ["PowerShell", "Cmd"],
                    "worklet_support": True,
                },
                "Mac": {
                    "agent_supported": True,
                    "versions": [
                        "macOS 15 (Sequoia)",
                        "macOS 14 (Sonoma)",
                        "macOS 13 (Ventura)",
                        "macOS 12 (Monterey)",
                    ],
                    "shell_types": ["Bash", "Zsh"],
                    "worklet_support": True,
                },
                "Linux": {
                    "agent_supported": True,
                    "distributions": [
                        "Ubuntu 20.04, 22.04, 24.04",
                        "CentOS 7, 8, 9 Stream",
                        "Red Hat Enterprise Linux 7, 8, 9",
                        "Amazon Linux 2, 2023",
                        "Debian 10, 11, 12",
                        "Fedora (latest two releases)",
                        "Oracle Linux 7, 8, 9",
                        "SUSE Linux Enterprise 12, 15",
                        "openSUSE Leap 15",
                        "Rocky Linux 8, 9",
                        "Alma Linux 8, 9",
                    ],
                    "shell_types": ["Bash", "Zsh"],
                    "worklet_support": True,
                },
            },
            "usage_notes": [
                "Use os_family='Windows', 'Mac', or 'Linux' in policy configuration",
                "The os_name field on devices contains the full OS name (e.g., 'Microsoft Windows 11 Enterprise')",
                "Use search_devices to find devices by platform",
            ],
        }

    @server.resource(
        "resource://api/rate-limits",
        name="API Rate Limiting Guide",
        description=(
            "Rate limiting behavior for the Automox API and the MCP server's "
            "built-in rate limiter. Useful for understanding throttling behavior."
        ),
        mime_type="application/json",
    )
    def get_rate_limits() -> dict[str, Any]:
        return {
            "mcp_server_rate_limit": {
                "description": "Built-in sliding window rate limiter applied to all MCP tool calls",
                "max_calls": 30,
                "period_seconds": 60,
                "behavior": (
                    "Calls exceeding the limit are rejected immediately with a rate limit error. "
                    "The window slides — oldest calls expire after 60 seconds."
                ),
            },
            "automox_api_rate_limit": {
                "description": "Automox platform API rate limiting",
                "behavior": (
                    "Automox enforces server-side rate limits. When exceeded, the API returns "
                    "HTTP 429 (Too Many Requests). The MCP server surfaces this as an error."
                ),
                "recommendations": [
                    "Use compound tools (get_patch_tuesday_readiness, get_compliance_snapshot) "
                    "to reduce the number of individual API calls",
                    "Use pagination (limit/page parameters) to fetch manageable result sets",
                    "Avoid polling the same endpoint in tight loops",
                ],
            },
            "tips_for_efficient_usage": [
                "Start with compound tools for common questions — they combine multiple API calls",
                "Use device_health_metrics for fleet-wide stats instead of listing all devices",
                "Use MCP Resources (like this one) for reference data — they don't count as API calls",
                "Filter results at the API level (group_id, severity, etc.) rather than fetching everything",
            ],
        }


__all__ = ["register"]

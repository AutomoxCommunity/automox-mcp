"""Meta-tools for capability discovery."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..client import AutomoxClient

_DOMAIN_CATALOG: dict[str, list[tuple[str, str]]] = {
    "devices": [
        ("list_devices", "List devices with per-device detail"),
        ("device_detail", "Detailed info and recent activity for a device"),
        ("devices_needing_attention", "Devices flagged for immediate action"),
        ("search_devices", "Search by hostname, IP, tag, severity, or patch status"),
        ("device_health_metrics", "Aggregate fleet-wide health statistics"),
        ("get_device_inventory", "Detailed device inventory data"),
        ("get_device_inventory_categories", "Available inventory categories"),
        ("execute_device_command", "Issue scan/patch/reboot command"),
        ("get_device_full_profile", "Complete profile: detail + inventory + packages"),
    ],
    "device_search": [
        ("list_saved_searches", "List saved device searches"),
        ("advanced_device_search", "Execute advanced search with structured query"),
        ("device_search_typeahead", "Typeahead suggestions for search fields"),
        ("get_device_metadata_fields", "Available fields for device queries"),
        ("get_device_assignments", "Device-to-policy/group assignments"),
        ("get_device_by_uuid", "Get device by UUID (v2 endpoint)"),
    ],
    "policies": [
        ("policy_catalog", "List policies with type and status summaries"),
        ("policy_detail", "Configuration and recent history for a policy"),
        ("policy_health_overview", "Summarize recent policy activity"),
        ("policy_execution_timeline", "Recent executions for a policy"),
        ("policy_run_results", "Per-device results for a policy execution"),
        ("policy_compliance_stats", "Per-policy compliance statistics"),
        ("apply_policy_changes", "Create or update policies"),
        ("clone_policy", "Clone an existing policy"),
        ("delete_policy", "Delete a policy permanently"),
        ("execute_policy_now", "Execute a policy immediately"),
    ],
    "policy_history": [
        ("policy_runs_v2", "List policy runs with time-range and status filters"),
        ("policy_run_count", "Aggregate policy execution counts"),
        ("policy_runs_by_policy", "Runs grouped by policy for comparison"),
        ("policy_history_detail", "Policy history details by UUID"),
        ("policy_runs_for_policy", "Execution runs for a specific policy"),
        ("policy_run_detail_v2", "Per-device results for a run (UUID-based)"),
    ],
    "patches": [
        ("list_device_packages", "Software packages on a specific device"),
        ("search_org_packages", "Search packages across the organization"),
        ("patch_approvals_summary", "Pending patch approvals and severity"),
        ("decide_patch_approval", "Approve or reject a patch approval"),
        ("prepatch_report", "Pre-patch readiness report"),
    ],
    "groups": [
        ("list_server_groups", "List server groups with device counts"),
        ("get_server_group", "Details for a specific server group"),
        ("create_server_group", "Create a new server group"),
        ("update_server_group", "Update an existing server group"),
        ("delete_server_group", "Delete a server group"),
    ],
    "events": [
        ("list_events", "Organization events with optional filters"),
    ],
    "reports": [
        ("prepatch_report", "Pre-patch readiness report"),
        ("noncompliant_report", "Non-compliant devices report"),
        ("get_compliance_snapshot", "Combined compliance posture view"),
        ("get_patch_tuesday_readiness", "Patch Tuesday readiness view"),
    ],
    "audit": [
        ("audit_trail_user_activity", "Audit trail events by user and date"),
        ("audit_events_ocsf", "OCSF-formatted audit events with category filtering"),
    ],
    "webhooks": [
        ("list_webhook_event_types", "Available webhook event types"),
        ("list_webhooks", "All webhook subscriptions"),
        ("get_webhook", "Details for a specific webhook"),
        ("create_webhook", "Create a new webhook subscription"),
        ("update_webhook", "Update an existing webhook"),
        ("delete_webhook", "Delete a webhook"),
        ("test_webhook", "Send a test delivery"),
        ("rotate_webhook_secret", "Rotate signing secret"),
    ],
    "worklets": [
        ("search_worklet_catalog", "Search community worklet catalog"),
        ("get_worklet_detail", "Detailed worklet info with code"),
    ],
    "data_extracts": [
        ("list_data_extracts", "List available data extracts"),
        ("get_data_extract", "Get extract details and download info"),
        ("create_data_extract", "Request a new data extract"),
    ],
    "vuln_sync": [
        ("list_remediation_action_sets", "List vulnerability action sets"),
        ("get_action_set_detail", "Action set details"),
        ("get_action_set_actions", "Remediation actions for an action set"),
        ("get_action_set_issues", "Vulnerability issues for an action set"),
        ("get_action_set_solutions", "Solutions for an action set"),
        ("get_upload_formats", "Supported CSV upload formats"),
        ("upload_action_set", "Upload CSV remediation data"),
    ],
    "account": [
        ("invite_user_to_account", "Invite a user with zone assignments"),
        ("remove_user_from_account", "Remove a user by UUID"),
        ("list_org_api_keys", "List organization API keys (names only)"),
    ],
    "compound": [
        ("get_patch_tuesday_readiness", "Patch Tuesday readiness view"),
        ("get_compliance_snapshot", "Compliance posture view"),
        ("get_device_full_profile", "Complete device profile"),
    ],
}


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register capability discovery tools."""

    @server.tool(
        name="discover_capabilities",
        description=(
            "Discover available Automox MCP tools for a specific domain. "
            "Returns tool names and descriptions. "
            "Valid domains: devices, policies, patches, groups, events, "
            "reports, audit, webhooks, account, compound. "
            "Call with no domain to list all available domains."
        ),
    )
    async def discover_capabilities(
        domain: str | None = None,
    ) -> dict[str, Any]:
        if domain is None:
            return {
                "data": {
                    "available_domains": sorted(_DOMAIN_CATALOG.keys()),
                    "hint": "Pass a domain name to see its tools.",
                },
                "metadata": {},
            }

        domain_lower = domain.strip().lower()
        if domain_lower not in _DOMAIN_CATALOG:
            return {
                "data": {
                    "error": (
                        f"Unknown domain '{domain}'. "
                        f"Available: {', '.join(sorted(_DOMAIN_CATALOG.keys()))}"
                    ),
                    "available_domains": sorted(_DOMAIN_CATALOG.keys()),
                },
                "metadata": {},
            }

        tools = [
            {"name": name, "description": desc} for name, desc in _DOMAIN_CATALOG[domain_lower]
        ]

        return {
            "data": {
                "domain": domain_lower,
                "tool_count": len(tools),
                "tools": tools,
            },
            "metadata": {},
        }


__all__ = ["register"]

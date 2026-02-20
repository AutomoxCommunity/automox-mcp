"""Automox MCP workflows - consolidated exports."""

from __future__ import annotations

from . import account, audit, devices, events, groups, packages, policy, reports, webhooks
from .account import invite_user_to_account, remove_user_from_account
from .audit import audit_trail_user_activity
from .devices import (
    describe_device,
    issue_device_command,
    list_device_inventory,
    list_devices_needing_attention,
    search_devices,
    summarize_device_health,
)
from .events import list_events
from .groups import (
    create_server_group,
    delete_server_group,
    get_server_group,
    list_server_groups,
    update_server_group,
)
from .packages import list_device_packages, search_org_packages
from .policy import (
    apply_policy_changes,
    describe_policy,
    describe_policy_run_result,
    execute_policy,
    normalize_policy_operations_input,
    resolve_patch_approval,
    summarize_patch_approvals,
    summarize_policies,
    summarize_policy_activity,
    summarize_policy_execution_history,
)
from .reports import get_noncompliant_report, get_prepatch_report
from .webhooks import (
    create_webhook,
    delete_webhook,
    get_webhook,
    list_webhook_event_types,
    list_webhooks,
    rotate_webhook_secret,
    test_webhook,
    update_webhook,
)

__all__ = [
    "account",
    "audit",
    "devices",
    "events",
    "groups",
    "packages",
    "policy",
    "reports",
    "webhooks",
    "apply_policy_changes",
    "audit_trail_user_activity",
    "create_server_group",
    "create_webhook",
    "delete_server_group",
    "delete_webhook",
    "describe_device",
    "describe_policy",
    "describe_policy_run_result",
    "execute_policy",
    "get_noncompliant_report",
    "get_prepatch_report",
    "get_server_group",
    "get_webhook",
    "invite_user_to_account",
    "issue_device_command",
    "list_device_inventory",
    "list_device_packages",
    "list_devices_needing_attention",
    "list_events",
    "list_server_groups",
    "list_webhook_event_types",
    "list_webhooks",
    "normalize_policy_operations_input",
    "remove_user_from_account",
    "resolve_patch_approval",
    "rotate_webhook_secret",
    "search_devices",
    "search_org_packages",
    "summarize_device_health",
    "summarize_patch_approvals",
    "summarize_policies",
    "summarize_policy_activity",
    "summarize_policy_execution_history",
    "test_webhook",
    "update_server_group",
    "update_webhook",
]

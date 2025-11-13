"""Automox MCP workflows - consolidated exports."""

from __future__ import annotations

from . import account, audit, devices, policy
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

__all__ = [
    "account",
    "audit",
    "devices",
    "policy",
    "audit_trail_user_activity",
    "apply_policy_changes",
    "describe_device",
    "describe_policy",
    "describe_policy_run_result",
    "execute_policy",
    "normalize_policy_operations_input",
    "invite_user_to_account",
    "issue_device_command",
    "list_device_inventory",
    "list_devices_needing_attention",
    "remove_user_from_account",
    "resolve_patch_approval",
    "search_devices",
    "summarize_device_health",
    "summarize_policies",
    "summarize_policy_activity",
    "summarize_policy_execution_history",
    "summarize_patch_approvals",
]

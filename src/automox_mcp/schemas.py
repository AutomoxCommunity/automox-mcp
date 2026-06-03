"""Pydantic models for MCP tool inputs and outputs."""

from __future__ import annotations

import json
from datetime import date as Date
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class ForbidExtraModel(BaseModel):
    """Base model that disallows unexpected parameters."""

    model_config = ConfigDict(extra="forbid")


class OrgIdContextMixin(BaseModel):
    """Shared org_id field stored in the model but excluded from payloads."""

    org_id: int = Field(exclude=True)


class OrgIdRequiredMixin(BaseModel):
    """Org-scoped models that must explicitly receive an org_id."""

    org_id: int = Field(description="Organization ID")


class PaginationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")
    current_page: int | None = Field(None, description="Current page index")
    total_pages: int | None = Field(None, description="Total number of pages")
    total_count: int | None = Field(None, description="Total record count")
    limit: int | None = Field(None, description="Page size")
    previous: str | None = Field(None, description="Link to previous page")
    next: str | None = Field(None, description="Link to next page")
    deprecated_endpoint: bool = Field(
        False, description="Whether Automox marks the endpoint deprecated"
    )


class ToolResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    data: Any
    metadata: PaginationMetadata


class AuditTrailEventsParams(OrgIdContextMixin, ForbidExtraModel):
    date: Date = Field(description="Date to query for audit trail events")
    actor_email: str | None = Field(
        None,
        description=(
            "Filter events by the actor email address. Partial values are allowed "
            "and will trigger a lookup."
        ),
    )
    actor_uuid: UUID | None = Field(None, description="Filter events by the actor Automox UUID")
    actor_name: str | None = Field(
        None,
        description=(
            "Optional display name to resolve into an Automox user when the email is unknown."
        ),
    )
    cursor: str | None = Field(
        None,
        description="Resume the search from this Automox event cursor",
        max_length=2000,
    )
    limit: int | None = Field(
        None,
        ge=1,
        le=500,
        description="Maximum number of events to request from Automox (1-500)",
    )
    include_raw_events: bool | None = Field(
        False,
        description="Include sanitized raw event payloads for deeper inspection",
    )
    org_uuid: UUID | None = Field(
        None,
        description="Organization UUID override. Defaults to resolving from Automox configuration.",
    )


class RunDetailParams(ForbidExtraModel):
    org_uuid: UUID
    policy_uuid: UUID
    exec_token: UUID
    sort: str | None = Field(None, max_length=100)
    result_status: str | None = Field(None, max_length=100)
    device_name: str | None = Field(None, max_length=500)
    page: int | None = Field(None, ge=0)
    limit: int | None = Field(None, ge=1, le=5000)
    max_output_length: int | None = Field(None, ge=16, le=20000)


class PolicyHealthSummaryParams(ForbidExtraModel):
    org_uuid: UUID
    window_days: int | None = Field(7, ge=1, le=90)
    top_failures: int | None = Field(5, ge=1, le=25)
    max_runs: int | None = Field(200, ge=1, le=5000)


class PolicyExecutionTimelineParams(ForbidExtraModel):
    org_uuid: UUID
    policy_uuid: UUID
    report_days: int | None = Field(7, ge=1, le=180)
    limit: int | None = Field(50, ge=1, le=5000)


class PolicyDefinition(BaseModel):
    """Generic policy definition payload passed to Automox.

    Uses ``extra="ignore"`` to silently drop unrecognized fields rather than
    passing arbitrary keys to the API (``extra="allow"``) or rejecting the
    request entirely (``extra="forbid"`` — too strict for forward-compat).
    """

    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(None, description="Display name for the policy")
    policy_type_name: Literal["patch", "custom", "required_software"] | None = Field(
        None,
        description="Policy type. Required when creating a policy.",
    )
    configuration: dict[str, Any] | None = Field(
        None,
        description="Policy configuration block exactly as expected by Automox.",
    )
    schedule_days: int | None = Field(
        None,
        ge=0,
        le=254,
        description="Bitmask representing scheduled days of the week (max 254 = bits 1-7).",
    )
    schedule_weeks_of_month: int | None = Field(
        None,
        ge=0,
        le=62,
        description="Bitmask representing scheduled weeks of the month (max 62 = bits 1-5).",
    )
    schedule_months: int | None = Field(
        None,
        ge=0,
        le=8190,
        description="Bitmask representing scheduled months of the year (max 8190 = bits 1-12).",
    )
    schedule_time: str | None = Field(
        None,
        description="Scheduled execution time in HH:MM format.",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
    )
    use_scheduled_timezone: bool | None = Field(
        None, description="When true, schedule is interpreted in UTC."
    )
    scheduled_timezone: str | None = Field(
        None,
        description=(
            "UTC offset string required when use_scheduled_timezone is true (e.g. 'UTC+0000')."
        ),
        pattern=r"^UTC[+-]\d{4}$",
    )
    server_groups: list[int] | None = Field(
        None,
        description="Server group IDs targeted by the policy.",
    )
    notes: str | None = Field(None, description="Operator notes associated with the policy.")
    policy_template_id: int | None = Field(
        None, description="Optional Automox policy template identifier."
    )


class CreatePolicyOperation(ForbidExtraModel):
    """Instruction to create a brand-new Automox policy.

    Example:
        {
            "action": "create",
            "policy": {
                "name": "Chrome Patch Policy",
                "policy_type_name": "patch",
                "configuration": {
                    "patch_rule": "filter",
                    "filters": ["*Google Chrome*"]
                },
                "schedule": {
                    "days": ["monday"],
                    "time": "02:00"
                },
                "server_groups": []
            }
        }
    """

    action: Literal["create"] = Field(
        "create",
        description=(
            "REQUIRED: Must be 'create' (not 'operation'). Creates a new policy "
            "with the provided definition."
        ),
    )
    policy: PolicyDefinition = Field(
        description=(
            "Complete policy definition to submit. Must include name, "
            "policy_type_name, configuration, and schedule."
        )
    )


class UpdatePolicyOperation(ForbidExtraModel):
    """Instruction to update an existing policy.

    Example:
        {
            "action": "update",
            "policy_id": 12345,
            "policy": {
                "name": "Updated Chrome Policy"
            },
            "merge_existing": true
        }
    """

    action: Literal["update"] = Field(
        "update",
        description=(
            "REQUIRED: Must be 'update' (not 'operation'). Updates an existing policy "
            "by ID with the supplied changes."
        ),
    )
    policy_id: int = Field(description="Existing Automox policy ID to update.", ge=1)
    policy: PolicyDefinition = Field(
        description=(
            "Policy fields to apply. When merge_existing is true, these values "
            "override the current policy."
        )
    )
    merge_existing: bool | None = Field(
        True,
        description=(
            "When true, fetch the current policy and merge these fields on top "
            "before sending to Automox."
        ),
    )


PolicyOperation = Annotated[
    CreatePolicyOperation | UpdatePolicyOperation,
    Field(discriminator="action"),
]


class PolicyChangeRequestParams(OrgIdContextMixin, ForbidExtraModel):
    """Structured request for creating or updating Automox policies."""

    operations: list[PolicyOperation] = Field(
        description="Ordered list of policy create/update operations to perform.",
        min_length=1,
        max_length=50,
    )
    preview: bool | None = Field(
        False,
        description="If true, return the intended changes without calling the Automox API.",
    )


class DevicesNeedingAttentionParams(OrgIdContextMixin, ForbidExtraModel):
    group_id: int | None = Field(None, ge=1)
    limit: int | None = Field(20, ge=1, le=200)


class DeviceInventoryOverviewParams(OrgIdContextMixin, ForbidExtraModel):
    group_id: int | None = Field(None, ge=1)
    limit: int | None = Field(500, ge=1, le=500)
    include_unmanaged: bool | None = Field(
        True, description="Include unmanaged devices in the summary"
    )
    policy_status: str | None = Field(
        None, description="Filter devices by normalized policy status (e.g., 'non-compliant')"
    )
    managed: bool | None = Field(
        None, description="Filter devices by managed status (True for managed, False for unmanaged)"
    )


class DeviceDetailParams(OrgIdContextMixin, ForbidExtraModel):
    device_id: int = Field(description="Device identifier", ge=1)
    include_packages: bool | None = Field(
        False, description="Include a sample of installed packages"
    )
    include_inventory: bool | None = Field(
        True, description="Include categorized inventory details"
    )
    include_queue: bool | None = Field(True, description="Include upcoming queued commands")
    include_raw_details: bool | None = Field(
        False, description="Include a sanitized slice of the full Automox device payload"
    )


class DeviceInventoryParams(OrgIdContextMixin, ForbidExtraModel):
    device_id: int = Field(description="Device identifier", ge=1)
    category: str | None = Field(
        None,
        description=(
            "Inventory category to retrieve. Use get_device_inventory_categories "
            "to discover available categories. Common values: Hardware, Health, "
            "Network, Security, Services, Summary, System, Users."
        ),
    )


class DeviceIdOnlyParams(OrgIdContextMixin, ForbidExtraModel):
    device_id: int = Field(description="Device identifier", ge=1)


class DeviceSearchParams(OrgIdContextMixin, ForbidExtraModel):
    hostname_contains: str | None = Field(
        None, description="Match devices whose hostname or custom name contains this text"
    )
    ip_address: str | None = Field(None, description="Match devices with this IP address")
    tag: str | None = Field(None, description="Match devices containing this tag")
    patch_status: Literal["missing"] | None = Field(
        None,
        description=(
            "Filter by patch status. Only 'missing' is supported (matches uninstalled patches)."
        ),
    )
    severity: list[str] | str | None = Field(
        None,
        description=(
            "Filter by severity of missing patches (e.g., 'critical'). Accepts a single value "
            "or list."
        ),
    )
    managed: bool | None = Field(None, description="Filter by managed status")
    group_id: int | None = Field(None, ge=1, description="Restrict to a specific server group")
    limit: int | None = Field(50, ge=1, le=500, description="Maximum number of devices to return")


class DeviceHealthSummaryParams(OrgIdContextMixin, ForbidExtraModel):
    group_id: int | None = Field(
        None, ge=1, description="Limit the summary to a specific server group"
    )
    include_unmanaged: bool | None = Field(
        False, description="Include unmanaged devices in calculations"
    )
    limit: int | None = Field(
        500,
        ge=1,
        le=500,
        description="Maximum number of devices to sample from Automox (1-500)",
    )
    max_stale_devices: int | None = Field(
        25,
        ge=0,
        le=200,
        description=(
            "Maximum number of stale devices to include in the response. "
            "Set to 0 to omit the list or null to include all."
        ),
    )


class PatchApprovalSummaryParams(OrgIdContextMixin, ForbidExtraModel):
    status: str | None = Field(
        None, description="Filter approvals by status (e.g., 'pending', 'approved', 'rejected')"
    )
    limit: int | None = Field(
        25, ge=1, le=200, description="Maximum approvals to include in the summary"
    )


class PatchApprovalDecisionParams(OrgIdContextMixin, ForbidExtraModel):
    approval_id: int = Field(description="Patch approval request identifier", ge=1)
    decision: Literal["approve", "approved", "reject", "rejected", "deny"] = Field(
        description="Approve or deny the request"
    )
    notes: str | None = Field(None, description="Optional notes to include with the decision")


class PolicySummaryParams(OrgIdContextMixin, ForbidExtraModel):
    page: int | None = Field(
        0, ge=0, description="Page number when paginating through the policy catalog (0-indexed)"
    )
    limit: int | None = Field(20, ge=1, le=200)
    include_inactive: bool | None = Field(
        False, description="Include inactive policies in the summary"
    )
    include_stats: bool | None = Field(
        False,
        description=(
            "Include the per-policy compliance stats array. Off by default — the "
            "stats payload is large and previously caused response truncation that "
            "hid policies. Use policy_compliance_stats for a focused breakdown."
        ),
    )


class PolicyDetailParams(OrgIdContextMixin, ForbidExtraModel):
    policy_id: int = Field(description="Policy identifier", ge=1)
    include_recent_runs: int | None = Field(5, ge=0, le=50)


class GetDevicePackagesParams(ForbidExtraModel):
    device_id: int = Field(description="Device ID")
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


class GetPolicyStatsParams(OrgIdContextMixin, ForbidExtraModel):
    pass  # Only requires org_id from context


# ============================================================================
# GROUP ENDPOINT SCHEMAS
# ============================================================================


class ListServerGroupsParams(ForbidExtraModel):
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


class GetServerGroupParams(ForbidExtraModel):
    group_id: int = Field(description="Server Group ID")


# ============================================================================
# REPORT ENDPOINT SCHEMAS
# ============================================================================


class GetPrepatchReportParams(ForbidExtraModel):
    group_id: int | None = Field(None, description="Filter by Server Group ID")
    limit: int | None = Field(None, ge=1, le=500, description="Maximum number of results")
    offset: int | None = Field(None, ge=0, description="Offset for pagination")


class GetNeedsAttentionReportParams(ForbidExtraModel):
    group_id: int | None = Field(None, description="Filter by Server Group ID")
    limit: int | None = Field(None, ge=1, le=500, description="Maximum number of results")
    offset: int | None = Field(None, ge=0, description="Offset for pagination")


# ============================================================================
# EVENT ENDPOINT SCHEMAS
# ============================================================================


class GetEventsParams(ForbidExtraModel):
    page: int | None = Field(None, ge=0, description="Page number")
    count_only: bool | None = Field(None, description="Return only count, not full data")
    policy_id: int | None = Field(None, description="Filter by Policy ID")
    server_id: int | None = Field(None, description="Filter by Server/Device ID")
    user_id: int | None = Field(None, description="Filter by User ID")
    event_name: str | None = Field(None, description="Filter by event name", max_length=200)
    start_date: str | None = Field(
        None,
        description="Start date filter (ISO format)",
        max_length=30,
    )
    end_date: str | None = Field(None, description="End date filter (ISO format)", max_length=30)
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


# ============================================================================
# PACKAGE ENDPOINT SCHEMAS
# ============================================================================


class GetOrganizationPackagesParams(OrgIdRequiredMixin, ForbidExtraModel):
    include_unmanaged: bool | None = Field(None, description="Include unmanaged packages")
    awaiting: bool | None = Field(None, description="Show packages awaiting installation")
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


# ============================================================================
# WRITE OPERATION SCHEMAS
# ============================================================================


class ExecutePolicyParams(OrgIdContextMixin, ForbidExtraModel):
    policy_id: int = Field(description="Policy ID to execute", ge=1)
    action: Literal["remediateAll", "remediateServer"] = Field(
        description="Execute on all devices or a specific device"
    )
    device_id: int | None = Field(
        None, description="Device ID (required for remediateServer action)", ge=1
    )


class IssueDeviceCommandParams(OrgIdContextMixin, ForbidExtraModel):
    device_id: int = Field(description="Device ID to send command to", ge=1)
    command_type: Literal[
        "scan", "get_os", "refresh", "patch", "patch_all", "patch_specific", "reboot"
    ] = Field(description="Command to execute on the device")
    patch_names: str | None = Field(
        None,
        description="Comma-separated patch names (required for patch_specific command)",
        max_length=2000,
        pattern=r"^[a-zA-Z0-9 _.,:;()\[\]+\-/]+$",
    )


class RunRemediationActionsParams(OrgIdRequiredMixin, ForbidExtraModel):
    action_set_id: int = Field(description="Action set ID", ge=1)
    actions: list[dict[str, Any]] = Field(
        description=(
            "Remediation actions to execute. Each: "
            "{'action': 'patch-now'|'patch-with-worklet', 'solution_id': int, "
            "'devices': [int, ...], 'worklet_id': int (required for patch-with-worklet)}"
        ),
        min_length=1,
        max_length=50,
    )

    @model_validator(mode="after")
    def _validate_actions(self) -> RunRemediationActionsParams:
        for action in self.actions:
            kind = action.get("action")
            if kind not in {"patch-now", "patch-with-worklet"}:
                raise ValueError("action must be 'patch-now' or 'patch-with-worklet'")
            if "solution_id" not in action:
                raise ValueError("each action requires 'solution_id'")
            devices = action.get("devices")
            if not isinstance(devices, list) or not devices:
                raise ValueError("each action requires a non-empty 'devices' list")
            if kind == "patch-with-worklet" and "worklet_id" not in action:
                raise ValueError("'patch-with-worklet' requires 'worklet_id'")
        return self


class PolicyDeviceFilterPreviewParams(OrgIdRequiredMixin, ForbidExtraModel):
    device_filters: list[dict[str, Any]] | None = Field(
        None, description="Device-filter clauses ({field, op, value}) to preview"
    )
    server_groups: list[int] | None = Field(None, description="Server-group IDs to include")
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


class ListDevicesForPoliciesParams(ForbidExtraModel):
    policies: list[str] = Field(
        description="Policy UUIDs to list affected devices for",
        min_length=1,
        max_length=200,
    )

    @model_validator(mode="after")
    def _validate_policy_uuids(self) -> ListDevicesForPoliciesParams:
        for policy_uuid in self.policies:
            UUID(policy_uuid)  # reject malformed policy UUIDs
        return self


class BatchUpdateDevicesParams(OrgIdRequiredMixin, ForbidExtraModel):
    devices: list[int] = Field(
        description="Device (server) IDs to update",
        min_length=1,
        max_length=500,
    )
    actions: list[dict[str, Any]] = Field(
        description=(
            "Actions to apply to each device, e.g. "
            "{'attribute': 'tags', 'action': 'apply'|'remove', 'value': [...]}"
        ),
        min_length=1,
        max_length=50,
    )

    @model_validator(mode="after")
    def _validate_actions(self) -> BatchUpdateDevicesParams:
        for action in self.actions:
            if "attribute" not in action or "action" not in action:
                raise ValueError("each action requires 'attribute' and 'action'")
        return self


class UpdateDeviceParams(OrgIdRequiredMixin, ForbidExtraModel):
    device_id: int = Field(description="Device (server) ID to update", ge=1)
    custom_name: str | None = Field(
        None, description="Friendly display name for the device", max_length=255
    )
    server_group_id: int | None = Field(
        None, ge=0, description="Server group to move the device into"
    )
    exception: bool | None = Field(
        None, description="Whether the device is excluded from policy enforcement"
    )
    tags: list[str] | None = Field(
        None, description="Replacement tag list for the device", max_length=200
    )
    ip_addrs: list[str] | None = Field(
        None, description="Replacement IP address list for the device", max_length=200
    )

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> UpdateDeviceParams:
        if all(
            value is None
            for value in (
                self.custom_name,
                self.server_group_id,
                self.exception,
                self.tags,
                self.ip_addrs,
            )
        ):
            raise ValueError(
                "update_device requires at least one of: custom_name, server_group_id, "
                "exception, tags, ip_addrs"
            )
        return self


class ClonePolicyParams(OrgIdContextMixin, ForbidExtraModel):
    policy_id: int = Field(description="Policy ID to clone")
    name: str | None = Field(
        None, description="Name for the cloned policy (defaults to '<source> (Clone)')"
    )
    server_groups: list[int] | None = Field(None, description="Server group IDs for the clone")
    target_zone_ids: list[str] | None = Field(
        None,
        description=(
            "Target zone UUIDs for a multi-zone clone (patch policies only). When set, "
            "clones the source patch policy into each zone in one server-side call; "
            "cannot be combined with name or server_groups."
        ),
        min_length=1,
        max_length=500,
    )

    @model_validator(mode="after")
    def _validate_clone_mode(self) -> ClonePolicyParams:
        if self.target_zone_ids is not None:
            if self.name is not None or self.server_groups is not None:
                raise ValueError(
                    "target_zone_ids (multi-zone clone) cannot be combined with "
                    "name or server_groups"
                )
            for zone_id in self.target_zone_ids:
                UUID(zone_id)  # reject malformed zone UUIDs
        return self


class DeletePolicyToolParams(OrgIdContextMixin, ForbidExtraModel):
    policy_id: int = Field(description="Policy ID to delete", ge=1)


class CreateServerGroupParams(ForbidExtraModel):
    name: str = Field(description="Group name")
    refresh_interval: int = Field(description="Refresh interval in minutes", ge=1, le=525600)
    parent_server_group_id: int = Field(description="Parent group ID (required by API)")
    ui_color: str | None = Field(
        None,
        description="UI color for group",
        pattern=r"^#[0-9a-fA-F]{6}$",
    )
    notes: str | None = Field(None, description="Group notes")
    policies: list[int] | None = Field(None, description="Policy IDs to assign")


class UpdateServerGroupParams(ForbidExtraModel):
    group_id: int = Field(description="Server group ID")
    name: str = Field(description="Group name")
    refresh_interval: int = Field(description="Refresh interval in minutes", ge=1, le=525600)
    parent_server_group_id: int = Field(description="Parent group ID (required by API)")
    ui_color: str | None = Field(
        None,
        description="UI color for group",
        pattern=r"^#[0-9a-fA-F]{6}$",
    )
    notes: str | None = Field(None, description="Group notes")
    policies: list[int] | None = Field(None, description="Policy IDs to assign")


class ZoneAssignment(ForbidExtraModel):
    zone_id: str = Field(description="Automox zone identifier", min_length=1)
    rbac_role: Literal[
        "zone-admin",
        "billing-admin",
        "read-only",
        "zone-operator",
        "patch-operator",
        "helpdesk-operator",
    ] = Field(description="Zone RBAC role to grant")


class InviteUserParams(ForbidExtraModel):
    account_id: UUID = Field(
        description=(
            "Account ID (UUID format, NOT the numeric organization ID - "
            "this is the account-level identifier)"
        )
    )
    email: EmailStr = Field(description="User email address")
    account_rbac_role: Literal["global-admin", "no-global-access"] = Field(
        description="Account-level role"
    )
    zone_assignments: list[ZoneAssignment] | None = Field(
        None,
        description=(
            "Zone access assignments (required for no-global-access). "
            "Each item should include zone_id and rbac_role."
        ),
    )

    @model_validator(mode="after")
    def _require_zone_assignments(self) -> InviteUserParams:
        if self.account_rbac_role == "no-global-access":
            if not self.zone_assignments:
                raise ValueError(
                    "Zone assignments are required when inviting a user with the "
                    "no-global-access account role. Provide at least one zone "
                    "assignment object like {'zone_id': '<ZONE_ID>', 'rbac_role': 'read-only'}. "
                    "Zones correspond to Automox organizations and differ from server groups."
                )
        return self


class DeleteServerGroupParams(OrgIdRequiredMixin, ForbidExtraModel):
    group_id: int = Field(description="Server group ID to delete")


class RemoveUserFromAccountParams(ForbidExtraModel):
    account_id: UUID = Field(description="Account ID (UUID)")
    user_id: UUID = Field(description="User UUID to remove from account")


# ------------------------------------------------------------------------
# Identity inspection — read-only (issue #91 category A)
# ------------------------------------------------------------------------


class ListUsersParams(OrgIdRequiredMixin, ForbidExtraModel):
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


class GetUserParams(OrgIdRequiredMixin, ForbidExtraModel):
    user_id: int = Field(description="User ID")


class GetAccountParams(ForbidExtraModel):
    account_id: UUID = Field(description="Account ID (UUID)")


class ListAccountRbacRolesParams(ForbidExtraModel):
    account_id: UUID = Field(description="Account ID (UUID)")


class GetAccountUserParams(ForbidExtraModel):
    account_id: UUID = Field(description="Account ID (UUID)")
    user_id: UUID = Field(description="User UUID")


class ListZonesForUserParams(ForbidExtraModel):
    account_id: UUID = Field(description="Account ID (UUID)")
    user_id: UUID = Field(description="User UUID")


class ListZonesParams(ForbidExtraModel):
    account_id: UUID = Field(description="Account ID (UUID)")
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


class GetZoneParams(ForbidExtraModel):
    account_id: UUID = Field(description="Account ID (UUID)")
    zone_id: UUID = Field(description="Zone (organization) UUID")


class ListZoneUsersParams(ForbidExtraModel):
    account_id: UUID = Field(description="Account ID (UUID)")
    zone_id: UUID = Field(description="Zone (organization) UUID")
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


# ------------------------------------------------------------------------
# Identity / zone / per-user-key writes (issue #91 category A, write slice)
# ------------------------------------------------------------------------


class CreateZoneParams(ForbidExtraModel):
    account_id: UUID = Field(description="Account ID (UUID)")
    name: str = Field(description="Zone name", min_length=1, max_length=200)


class UpdateUserParams(ForbidExtraModel):
    # NOTE: password fields are intentionally NOT accepted — exposing a
    # password-set path through an MCP tool is an account-takeover vector.
    user_id: int = Field(description="User ID")
    firstname: str | None = Field(None, description="First name", max_length=200)
    lastname: str | None = Field(None, description="Last name", max_length=200)
    email: str | None = Field(None, description="Email address", max_length=320)
    tfa_type: str | None = Field(None, description="Two-factor auth type", max_length=50)

    @model_validator(mode="after")
    def _require_a_field(self) -> UpdateUserParams:
        if not any((self.firstname, self.lastname, self.email, self.tfa_type)):
            raise ValueError("at least one of firstname/lastname/email/tfa_type must be provided")
        return self


class ListUserApiKeysParams(OrgIdRequiredMixin, ForbidExtraModel):
    user_id: int = Field(description="User ID")
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


class GetUserApiKeyParams(OrgIdRequiredMixin, ForbidExtraModel):
    user_id: int = Field(description="User ID")
    key_id: int = Field(description="API key ID")


class CreateUserApiKeyParams(OrgIdRequiredMixin, ForbidExtraModel):
    user_id: int = Field(description="User ID")
    name: str = Field(description="API key name", min_length=1, max_length=200)
    expires_at: str | None = Field(None, description="Expiry timestamp (ISO 8601)")


class UpdateUserApiKeyParams(OrgIdRequiredMixin, ForbidExtraModel):
    user_id: int = Field(description="User ID")
    key_id: int = Field(description="API key ID")
    is_enabled: bool = Field(description="Whether the key is enabled")


class DeleteUserApiKeyParams(OrgIdRequiredMixin, ForbidExtraModel):
    user_id: int = Field(description="User ID")
    key_id: int = Field(description="API key ID")


# ------------------------------------------------------------------------
# Global (account-scoped) API keys — no decrypt (issue #91 category B)
# ------------------------------------------------------------------------


class CreateGlobalApiKeyParams(ForbidExtraModel):
    name: str = Field(description="API key name", min_length=1, max_length=200)
    expires_at: str | None = Field(None, description="Expiry timestamp (ISO 8601)")


class UpdateGlobalApiKeyParams(ForbidExtraModel):
    key_id: int = Field(description="Global API key ID")
    is_enabled: bool = Field(description="Whether the key is enabled")


class DeleteGlobalApiKeyParams(ForbidExtraModel):
    key_id: int = Field(description="Global API key ID")


class ListDataExtractsParams(OrgIdRequiredMixin, ForbidExtraModel):
    pass


class GetDataExtractParams(OrgIdRequiredMixin, ForbidExtraModel):
    extract_id: str = Field(
        description="Data extract ID",
        max_length=200,
        pattern=r"^[a-zA-Z0-9_\-]+$",
    )


class ListOrgApiKeysParams(OrgIdRequiredMixin, ForbidExtraModel):
    pass


class ListOrganizationsParams(ForbidExtraModel):
    """List organizations visible to the API key (account-wide, not org-scoped)."""

    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


class ListActionSetsParams(OrgIdRequiredMixin, ForbidExtraModel):
    pass


class GetActionSetUploadFormatsParams(OrgIdRequiredMixin, ForbidExtraModel):
    pass


class GetActionSetParams(OrgIdRequiredMixin, ForbidExtraModel):
    action_set_id: int = Field(description="Action set ID")


class DeleteActionSetParams(OrgIdRequiredMixin, ForbidExtraModel):
    action_set_id: int = Field(description="Action set ID to delete", ge=1)


class DeleteActionSetsBulkParams(OrgIdRequiredMixin, ForbidExtraModel):
    action_set_ids: list[int] = Field(
        description="Action set IDs to delete",
        min_length=1,
        max_length=100,
    )

    @model_validator(mode="after")
    def _validate_ids(self) -> DeleteActionSetsBulkParams:
        for action_set_id in self.action_set_ids:
            if action_set_id < 1:
                raise ValueError("each action_set_id must be >= 1")
        return self


class GetActionSetIssuesParams(OrgIdRequiredMixin, ForbidExtraModel):
    action_set_id: int = Field(description="Action set ID")


class GetActionSetSolutionsParams(OrgIdRequiredMixin, ForbidExtraModel):
    action_set_id: int = Field(description="Action set ID")


class SearchWisParams(OrgIdRequiredMixin, ForbidExtraModel):
    query: str | None = Field(None, description="Search query", max_length=1000)


class GetWisItemParams(OrgIdRequiredMixin, ForbidExtraModel):
    item_id: str = Field(
        description="WIS item ID",
        max_length=200,
        pattern=r"^[a-zA-Z0-9_\-]+$",
    )


# ------------------------------------------------------------------------
# Additional POST Operation Params
# ------------------------------------------------------------------------


class CreateDataExtractParams(OrgIdRequiredMixin, ForbidExtraModel):
    extract_data: dict[str, Any] = Field(description="Data extract configuration")

    @model_validator(mode="after")
    def _limit_extract_data_size(self) -> CreateDataExtractParams:
        raw = json.dumps(self.extract_data, default=str)
        if len(raw) > 50_000:
            raise ValueError("extract_data payload exceeds 50 KB limit")
        return self


class UploadActionSetParams(OrgIdRequiredMixin, ForbidExtraModel):
    csv_content: str = Field(
        description=(
            "Raw CSV text of the remediation action set, e.g. "
            "'Hostname,CVE ID,Severity\\nhost1,CVE-2021-1234,High'. The required "
            "columns depend on the source — call get_upload_formats first."
        ),
        min_length=1,
        max_length=1_000_000,
    )
    source: Literal["generic", "qualys", "tenable", "crowd-strike", "rapid7"] = Field(
        "generic",
        description=(
            "CSV source/format. Sent as both the `source` query param and the "
            "`format` body field, which the endpoint requires to agree."
        ),
    )
    filename: str = Field(
        "action-set.csv",
        description="Upload filename; becomes the action set's display name in the console.",
        min_length=1,
        max_length=255,
    )


class UploadPolicyFileParams(OrgIdContextMixin, ForbidExtraModel):
    policy_id: int = Field(
        description="Required Software policy ID to attach the installer to.", ge=1
    )
    file_path: str = Field(
        description=(
            "Absolute path to the installer file on the machine running the MCP "
            "server. Must resolve to a regular file inside one of the "
            "AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS directories."
        ),
        min_length=1,
        max_length=4096,
    )


# ============================================================================
# POLICY HISTORY V2 SCHEMAS
# ============================================================================


class PolicyRunsV2Params(OrgIdRequiredMixin, ForbidExtraModel):
    start_time: str | None = Field(None, description="Start time filter (ISO format)")
    end_time: str | None = Field(None, description="End time filter (ISO format)")
    policy_name: str | None = Field(None, description="Filter by policy name", max_length=500)
    policy_uuid: UUID | None = Field(None, description="Filter by policy UUID")
    policy_type: str | None = Field(None, description="Filter by policy type", max_length=100)
    result_status: str | None = Field(None, description="Filter by result status", max_length=100)
    sort: str | None = Field(None, description="Sort order", max_length=100)
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=5000, description="Results per page")


class PolicyRunCountParams(OrgIdRequiredMixin, ForbidExtraModel):
    days: int | None = Field(None, ge=1, le=365, description="Number of days to look back")


class PolicyRunsByPolicyParams(OrgIdRequiredMixin, ForbidExtraModel):
    pass


class PolicyHistoryDetailParams(OrgIdRequiredMixin, ForbidExtraModel):
    policy_uuid: UUID = Field(description="Policy UUID")
    recent_runs_limit: int | None = Field(
        25,
        ge=0,
        le=200,
        description=(
            "Maximum number of recent run summaries to include under "
            "`data.recent_runs`. Set 0 to omit; default 25."
        ),
    )


class PolicyRunsForPolicyParams(OrgIdRequiredMixin, ForbidExtraModel):
    policy_uuid: UUID = Field(description="Policy UUID")
    report_days: int | None = Field(None, ge=1, le=365, description="Days to look back")
    sort: str | None = Field(None, description="Sort order", max_length=100)
    summary_only: bool = Field(
        False,
        description=(
            "When true, project each run to {policy_uuid, run_time, execution_token, "
            "run_count} and drop banner_stats. Use this to enumerate execution tokens "
            "for a policy with many runs without pulling per-run stats."
        ),
    )


class PolicyExecutionCountsParams(OrgIdRequiredMixin, ForbidExtraModel):
    start_time: str | None = Field(None, description="Start of the window (ISO 8601)")
    end_time: str | None = Field(None, description="End of the window (ISO 8601)")


class PolicyRunDetailV2Params(OrgIdRequiredMixin, ForbidExtraModel):
    policy_uuid: UUID = Field(description="Policy UUID")
    exec_token: UUID = Field(description="Execution token")
    sort: str | None = Field(None, description="Sort order", max_length=100)
    result_status: str | None = Field(None, description="Filter by result status", max_length=100)
    device_name: str | None = Field(None, description="Filter by device name", max_length=500)
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=5000, description="Results per page")


# ============================================================================
# AUDIT V2 (OCSF) SCHEMAS
# ============================================================================


class AuditEventsOcsfParams(OrgIdRequiredMixin, ForbidExtraModel):
    date: str = Field(description="Date to query (YYYY-MM-DD)", pattern=r"^\d{4}-\d{2}-\d{2}$")
    category_name: str | None = Field(None, description="OCSF event category name", max_length=200)
    type_name: str | None = Field(None, description="OCSF event type name", max_length=200)
    cursor: str | None = Field(None, description="Pagination cursor", max_length=2000)
    limit: int | None = Field(None, ge=1, le=500, description="Maximum events to return")


# ============================================================================
# ADVANCED DEVICE SEARCH SCHEMAS
# ============================================================================


class AdvancedDeviceSearchParams(ForbidExtraModel):
    query: dict[str, Any] | None = Field(
        None,
        description=(
            "Structured device-search spec. Carries a `filters` list of AND/OR "
            'groups, e.g. {"filters": [{"AND": [{"scope": "SOFTWARE", "field": '
            '"pkgDisplayName", "operator": "IN", "values": ["nginx"]}]}]}. '
            "May also include `sort`/`fields`. org scoping is added automatically."
        ),
    )

    @model_validator(mode="after")
    def _limit_query_size(self) -> AdvancedDeviceSearchParams:
        if self.query is not None:
            raw = json.dumps(self.query, default=str)
            if len(raw) > 50_000:
                raise ValueError("query payload exceeds 50 KB limit")
        return self

    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


class DeviceSearchTypeaheadParams(ForbidExtraModel):
    field: str = Field(description="Field name to get suggestions for", max_length=100)
    prefix: str = Field(description="Search prefix", max_length=500)


class DeviceByUuidParams(ForbidExtraModel):
    device_uuid: UUID = Field(description="Device UUID")


class GetSavedSearchParams(ForbidExtraModel):
    saved_search_id: str = Field(description="Saved search ID", min_length=1, max_length=200)


class CreateSavedSearchParams(ForbidExtraModel):
    name: str = Field(description="Saved search name", min_length=1, max_length=200)
    query: dict[str, Any] = Field(
        description=(
            "Structured device-search spec carrying a `filters` list (same syntax "
            "as advanced_device_search). org scoping is added automatically."
        )
    )
    description: str | None = Field(None, description="Optional description", max_length=1000)

    @model_validator(mode="after")
    def _limit_query_size(self) -> CreateSavedSearchParams:
        raw = json.dumps(self.query, default=str)
        if len(raw) > 50_000:
            raise ValueError("query payload exceeds 50 KB limit")
        return self


class UpdateSavedSearchParams(ForbidExtraModel):
    saved_search_id: str = Field(description="Saved search ID", min_length=1, max_length=200)
    name: str | None = Field(None, description="Saved search name", max_length=200)
    query: dict[str, Any] | None = Field(None, description="Structured device-search query")
    description: str | None = Field(None, description="Optional description", max_length=1000)

    @model_validator(mode="after")
    def _require_a_field(self) -> UpdateSavedSearchParams:
        if self.name is None and self.query is None and self.description is None:
            raise ValueError("at least one of name/query/description must be provided")
        if self.query is not None:
            raw = json.dumps(self.query, default=str)
            if len(raw) > 50_000:
                raise ValueError("query payload exceeds 50 KB limit")
        return self


class DeleteSavedSearchParams(ForbidExtraModel):
    saved_search_id: str = Field(description="Saved search ID", min_length=1, max_length=200)


class SavedSearchResultsParams(ForbidExtraModel):
    saved_search_id: str = Field(description="Saved search ID", min_length=1, max_length=200)
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


class CachedSearchResultsParams(ForbidExtraModel):
    search_id: str = Field(description="Search execution ID", min_length=1, max_length=200)
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


class AssignPoliciesToSavedSearchParams(ForbidExtraModel):
    saved_search_uuid: UUID = Field(description="Saved-search UUID")
    policy_ids: list[int] = Field(
        description="Policy IDs to assign to the saved-search result set",
        min_length=1,
        max_length=200,
    )


class SearchesByDeviceParams(ForbidExtraModel):
    device_uuid: UUID = Field(description="Device UUID")
    search_type: str | None = Field(
        None, description="Optional saved-search type filter", max_length=100
    )


class RunSavedSearchParams(ForbidExtraModel):
    search_id: str = Field(description="Saved-search UUID", min_length=1, max_length=200)
    page: int | None = Field(None, ge=0, description="Page number")
    size: int | None = Field(None, ge=1, le=500, description="Results per page")
    fields: list[str] | None = Field(
        None,
        description="Optional list of fields to project into each result row",
        max_length=200,
    )


class RefreshSearchCacheParams(ForbidExtraModel):
    search_id: str = Field(description="Saved-search UUID", min_length=1, max_length=200)


# ============================================================================
# SPLASHTOP REMOTE CONTROL SCHEMAS (2026-01-14)
# ============================================================================

# OS values accepted by the install / initiate-connection / force-disconnect /
# uninstall endpoints. The OpenAPI spec is inconsistent (initiate-connection
# enums ``windows|macos``; install/uninstall/force-disconnect examples are
# ``windows|mac|deb``). We accept the union and pass the value through; the
# upstream validates per-endpoint.
_SPLASHTOP_OS_FAMILIES: tuple[str, ...] = ("windows", "mac", "macos", "deb")
_SPLASHTOP_ACCOUNT_TYPES: tuple[str, ...] = ("BASIC", "PREMIUM", "NONE")
_SPLASHTOP_CONNECTION_TYPES: tuple[str, ...] = (
    "remote_control",
    "remote_command",
    "file_transfer",
    "registry_editor",
)
_SPLASHTOP_REQUEST_PERMISSIONS: tuple[str, ...] = ("not_needed", "ask_reject_on_timeout")


class SplashtopDeviceStatusParams(ForbidExtraModel):
    device_uuid: UUID = Field(description="Automox device UUID")


class SplashtopSessionStatusParams(ForbidExtraModel):
    device_uuid: UUID = Field(description="Automox device UUID")
    account_type: str | None = Field(
        None,
        description="Optional accountType filter (BASIC, PREMIUM, NONE)",
    )

    @model_validator(mode="after")
    def _validate_account_type(self) -> SplashtopSessionStatusParams:
        if self.account_type is not None and self.account_type not in _SPLASHTOP_ACCOUNT_TYPES:
            raise ValueError(
                f"account_type must be one of {_SPLASHTOP_ACCOUNT_TYPES}, got {self.account_type!r}"
            )
        return self


class SplashtopAttendedAccessGetParams(ForbidExtraModel):
    device_uuid: UUID = Field(description="Automox device UUID")


class SplashtopInstallParams(ForbidExtraModel):
    device_uuid: UUID = Field(description="Automox device UUID")
    os_family: str = Field(description="Device OS family", min_length=1, max_length=32)
    request_permission: str | None = Field(
        None,
        description=(
            "Install-time consent: 'not_needed' (silent install) or "
            "'ask_reject_on_timeout' (prompt the user, reject on timeout). "
            "Distinct from per-device attended-access for sessions."
        ),
    )
    organization_uuid: UUID | None = Field(None, description="Optional organization UUID")
    account_type: str | None = Field(
        None,
        description="Optional accountType (BASIC, PREMIUM, NONE)",
    )

    @model_validator(mode="after")
    def _validate_enums(self) -> SplashtopInstallParams:
        if self.os_family not in _SPLASHTOP_OS_FAMILIES:
            raise ValueError(
                f"os_family must be one of {_SPLASHTOP_OS_FAMILIES}, got {self.os_family!r}"
            )
        if (
            self.request_permission is not None
            and self.request_permission not in _SPLASHTOP_REQUEST_PERMISSIONS
        ):
            raise ValueError(f"request_permission must be one of {_SPLASHTOP_REQUEST_PERMISSIONS}")
        if self.account_type is not None and self.account_type not in _SPLASHTOP_ACCOUNT_TYPES:
            raise ValueError(f"account_type must be one of {_SPLASHTOP_ACCOUNT_TYPES}")
        return self


class SplashtopBulkActionParams(ForbidExtraModel):
    action: str = Field(description="Bulk action: 'install' or 'uninstall'")
    server_group_id: int | None = Field(None, ge=1, description="Optional server group ID")

    @model_validator(mode="after")
    def _validate_action(self) -> SplashtopBulkActionParams:
        if self.action not in {"install", "uninstall"}:
            raise ValueError("action must be 'install' or 'uninstall'")
        return self


class SplashtopInitiateConnectionParams(ForbidExtraModel):
    device_uuid: UUID = Field(description="Automox device UUID")
    os_family: str = Field(description="Device OS family (windows or macos)")
    connection_type: str = Field(
        description=(
            "Connection type (remote_control, remote_command, file_transfer, registry_editor)"
        )
    )
    account_type: str | None = Field(
        None,
        description="Optional accountType (BASIC, PREMIUM, NONE)",
    )

    @model_validator(mode="after")
    def _validate_enums(self) -> SplashtopInitiateConnectionParams:
        if self.os_family not in _SPLASHTOP_OS_FAMILIES:
            raise ValueError(
                f"os_family must be one of {_SPLASHTOP_OS_FAMILIES}, got {self.os_family!r}"
            )
        if self.connection_type not in _SPLASHTOP_CONNECTION_TYPES:
            raise ValueError(
                f"connection_type must be one of {_SPLASHTOP_CONNECTION_TYPES}, "
                f"got {self.connection_type!r}"
            )
        if self.account_type is not None and self.account_type not in _SPLASHTOP_ACCOUNT_TYPES:
            raise ValueError(f"account_type must be one of {_SPLASHTOP_ACCOUNT_TYPES}")
        return self


class SplashtopForceDisconnectParams(ForbidExtraModel):
    device_uuid: UUID = Field(description="Automox device UUID")
    os_family: str = Field(description="Device OS family")

    @model_validator(mode="after")
    def _validate_os(self) -> SplashtopForceDisconnectParams:
        if self.os_family not in _SPLASHTOP_OS_FAMILIES:
            raise ValueError(
                f"os_family must be one of {_SPLASHTOP_OS_FAMILIES}, got {self.os_family!r}"
            )
        return self


class SplashtopSetAttendedAccessParams(ForbidExtraModel):
    device_uuid: UUID = Field(description="Automox device UUID")
    required_attended_access: bool = Field(
        description=(
            "When True, end-user consent is required before sessions start. "
            "When False, sessions can start without end-user approval — "
            "review your organization's policy before disabling."
        )
    )


class SplashtopSetBulkAttendedAccessParams(ForbidExtraModel):
    device_uuids: list[UUID] = Field(
        description="Automox device UUIDs",
        min_length=1,
        max_length=500,
    )
    required_attended_access: bool = Field(
        description=(
            "When True, end-user consent is required before sessions start. "
            "When False, sessions can start without end-user approval — "
            "review your organization's policy before disabling."
        )
    )


class SplashtopUninstallParams(ForbidExtraModel):
    device_uuid: UUID = Field(description="Automox device UUID")
    os_family: str = Field(description="Device OS family")

    @model_validator(mode="after")
    def _validate_os(self) -> SplashtopUninstallParams:
        if self.os_family not in _SPLASHTOP_OS_FAMILIES:
            raise ValueError(
                f"os_family must be one of {_SPLASHTOP_OS_FAMILIES}, got {self.os_family!r}"
            )
        return self


# ============================================================================
# COMPOUND TOOL SCHEMAS
# ============================================================================


class PatchTuesdayReadinessParams(OrgIdRequiredMixin, ForbidExtraModel):
    group_id: int | None = Field(None, ge=1, description="Restrict to a specific server group")
    org_uuid: str | None = Field(None, description="Organization UUID (auto-resolved)")
    detail_limit: int = Field(
        10,
        ge=0,
        le=200,
        description=(
            "Cap each inner list (devices, approvals, patch policy schedules) at "
            "this size. 0 returns counts only — useful for a pure summary. Truncated "
            "sections surface `metadata.section_summaries.<key>` with the total, "
            "returned count, and the detail tool to call for the rest."
        ),
    )


class ComplianceSnapshotParams(OrgIdRequiredMixin, ForbidExtraModel):
    group_id: int | None = Field(None, ge=1, description="Restrict to a specific server group")
    detail_limit: int = Field(
        10,
        ge=0,
        le=200,
        description=(
            "Cap each inner list (noncompliant devices, stale devices) at this "
            "size. 0 returns counts only. Truncated sections surface "
            "`metadata.section_summaries.<key>` with the follow-up tool to call "
            "for the rest. See compound-tool contract in the Pagination docs."
        ),
    )


class DeviceFullProfileParams(OrgIdRequiredMixin, ForbidExtraModel):
    device_id: int = Field(description="Device identifier", ge=1)
    max_packages: int = Field(
        25,
        ge=0,
        le=500,
        description=(
            "Legacy alias for `detail_limit`, retained for backwards-compat. "
            "Used when `detail_limit` is omitted."
        ),
    )
    detail_limit: int | None = Field(
        None,
        ge=0,
        le=500,
        description=(
            "Cap on the `packages.packages` inner list. When omitted falls "
            "back to `max_packages`. 0 returns counts only. Truncated sections "
            "surface `metadata.section_summaries.<key>` with the follow-up "
            "tool to call for the rest. See the compound-tool contract in the "
            "Pagination docs."
        ),
    )

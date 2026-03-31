"""Pydantic models for MCP tool inputs and outputs."""

from __future__ import annotations

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
        le=30,
        description="Bitmask representing scheduled weeks of the month (max 30 = bits 1-4).",
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
    start_date: str | None = Field(None, description="Start date filter (ISO format)", max_length=30)
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


class ClonePolicyParams(OrgIdContextMixin, ForbidExtraModel):
    policy_id: int = Field(description="Policy ID to clone")
    name: str | None = Field(
        None, description="Name for the cloned policy (defaults to '<source> (Clone)')"
    )
    server_groups: list[int] | None = Field(None, description="Server group IDs for the clone")


class DeletePolicyToolParams(OrgIdContextMixin, ForbidExtraModel):
    policy_id: int = Field(description="Policy ID to delete", ge=1)


class CreateServerGroupParams(ForbidExtraModel):
    name: str = Field(description="Group name")
    refresh_interval: int = Field(description="Refresh interval in minutes", ge=1, le=525600)
    parent_server_group_id: int = Field(description="Parent group ID (required by API)")
    ui_color: str | None = Field(None, description="UI color for group", pattern=r"^#[0-9a-fA-F]{6}$")
    notes: str | None = Field(None, description="Group notes")
    policies: list[int] | None = Field(None, description="Policy IDs to assign")


class UpdateServerGroupParams(ForbidExtraModel):
    group_id: int = Field(description="Server group ID")
    name: str = Field(description="Group name")
    refresh_interval: int = Field(description="Refresh interval in minutes", ge=1, le=525600)
    parent_server_group_id: int = Field(description="Parent group ID (required by API)")
    ui_color: str | None = Field(None, description="UI color for group", pattern=r"^#[0-9a-fA-F]{6}$")
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


class ListDataExtractsParams(OrgIdRequiredMixin, ForbidExtraModel):
    pass


class GetDataExtractParams(OrgIdRequiredMixin, ForbidExtraModel):
    extract_id: str = Field(description="Data extract ID", max_length=200, pattern=r"^[a-zA-Z0-9_\-]+$")


class ListOrgApiKeysParams(OrgIdRequiredMixin, ForbidExtraModel):
    pass


class ListActionSetsParams(OrgIdRequiredMixin, ForbidExtraModel):
    pass


class GetActionSetUploadFormatsParams(OrgIdRequiredMixin, ForbidExtraModel):
    pass


class GetActionSetParams(OrgIdRequiredMixin, ForbidExtraModel):
    action_set_id: int = Field(description="Action set ID")


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
        import json

        raw = json.dumps(self.extract_data, default=str)
        if len(raw) > 50_000:
            raise ValueError("extract_data payload exceeds 50 KB limit")
        return self


class UploadActionSetParams(OrgIdRequiredMixin, ForbidExtraModel):
    action_set_data: dict[str, Any] = Field(description="Action set upload data")

    @model_validator(mode="after")
    def _limit_action_set_data_size(self) -> UploadActionSetParams:
        import json

        raw = json.dumps(self.action_set_data, default=str)
        if len(raw) > 50_000:
            raise ValueError("action_set_data payload exceeds 50 KB limit")
        return self


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


class PolicyRunsForPolicyParams(OrgIdRequiredMixin, ForbidExtraModel):
    policy_uuid: UUID = Field(description="Policy UUID")
    report_days: int | None = Field(None, ge=1, le=365, description="Days to look back")
    sort: str | None = Field(None, description="Sort order", max_length=100)


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
    query: dict[str, Any] | None = Field(None, description="Structured query for device search")

    @model_validator(mode="after")
    def _limit_query_size(self) -> AdvancedDeviceSearchParams:
        if self.query is not None:
            import json

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


# ============================================================================
# COMPOUND TOOL SCHEMAS
# ============================================================================


class PatchTuesdayReadinessParams(OrgIdRequiredMixin, ForbidExtraModel):
    group_id: int | None = Field(None, ge=1, description="Restrict to a specific server group")
    org_uuid: str | None = Field(None, description="Organization UUID (auto-resolved)")


class ComplianceSnapshotParams(OrgIdRequiredMixin, ForbidExtraModel):
    group_id: int | None = Field(None, ge=1, description="Restrict to a specific server group")


class DeviceFullProfileParams(OrgIdRequiredMixin, ForbidExtraModel):
    device_id: int = Field(description="Device identifier", ge=1)
    max_packages: int = Field(25, ge=0, le=500, description="Max packages to include")

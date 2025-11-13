"""Pydantic models for MCP tool inputs and outputs."""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime
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


class AccountIdMixin(BaseModel):
    """Shared account_id field used by account-level endpoints."""

    account_id: str = Field(description="Account ID (UUID)")


class PaginationMixin(BaseModel):
    """Standard pagination arguments used by several list endpoints."""

    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


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


class ListPoliciesParams(ForbidExtraModel):
    org_uuid: UUID
    start_time: datetime | None = None
    end_time: datetime | None = None


class ListPolicyRunsParams(ForbidExtraModel):
    org_uuid: UUID
    start_time: datetime | None = None
    end_time: datetime | None = None
    policy_name: str | None = None
    policy_uuid: UUID | None = None
    policy_type: str | None = None
    result_status: str | None = None
    sort: str | None = None
    page: int | None = Field(None, ge=0)
    limit: int | None = Field(None, ge=1, le=5000)


class RunsForPolicyParams(ForbidExtraModel):
    org_uuid: UUID
    policy_uuid: UUID
    report_days: int | None = Field(None, ge=1)
    sort: str | None = None


class RunDetailParams(ForbidExtraModel):
    org_uuid: UUID
    policy_uuid: UUID
    exec_token: UUID
    sort: str | None = None
    result_status: str | None = None
    device_name: str | None = None
    page: int | None = Field(None, ge=0)
    limit: int | None = Field(None, ge=1, le=5000)
    max_output_length: int | None = Field(None, ge=16, le=20000)


class RunCountParams(ForbidExtraModel):
    org_uuid: UUID
    days: int | None = Field(None, ge=1)


class PolicyHealthSummaryParams(ForbidExtraModel):
    org_uuid: UUID
    window_days: int | None = Field(7, ge=1, le=90)
    top_failures: int | None = Field(5, ge=1, le=25)
    max_runs: int | None = Field(200, ge=1, le=5000)


class PolicyExecutionTimelineParams(ForbidExtraModel):
    org_uuid: UUID
    policy_uuid: UUID
    report_days: int | None = Field(7, ge=1, le=180)
    limit: int | None = Field(50, ge=10, le=200)


class PolicyDefinition(BaseModel):
    """Generic policy definition payload passed to Automox."""

    model_config = ConfigDict(extra="allow")

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
        description="Bitmask representing scheduled days of the week.",
    )
    schedule_weeks_of_month: int | None = Field(
        None,
        ge=0,
        description="Bitmask representing scheduled weeks of the month.",
    )
    schedule_months: int | None = Field(
        None,
        ge=0,
        description="Bitmask representing scheduled months of the year.",
    )
    schedule_time: str | None = Field(
        None,
        description="Scheduled execution time in HH:MM format.",
        pattern=r"^\d{2}:\d{2}$",
    )
    use_scheduled_timezone: bool | None = Field(
        None, description="When true, schedule is interpreted in UTC."
    )
    scheduled_timezone: str | None = Field(
        None,
        description=(
            "UTC offset string required when use_scheduled_timezone is true (e.g. 'UTC+0000')."
        ),
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
        description="Ordered list of policy create/update operations to perform.", min_length=1
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


class ListDevicesParams(ForbidExtraModel):
    group_id: int | None = Field(None, description="Filter by Server Group ID")
    managed: bool | None = Field(None, description="Filter by managed status")
    patch_status: str | None = Field(None, description="Filter by patch status (e.g., 'missing')")
    limit: int | None = Field(None, ge=1, le=500, description="Number of results (1-500)")
    page: int | None = Field(None, ge=0, description="Page number (0-indexed)")


# ============================================================================
# DEVICE ENDPOINT SCHEMAS
# ============================================================================


class GetDeviceParams(ForbidExtraModel):
    device_id: int = Field(description="Device ID")
    include_details: bool | None = Field(None, description="Include detailed device information")
    include_server_events: bool | None = Field(None, description="Include server event history")
    include_next_patch_time: bool | None = Field(
        None, description="Include next scheduled patch time"
    )
    exclude_policy_status: bool | None = Field(
        None, description="Exclude policy status information"
    )


class GetDevicePackagesParams(ForbidExtraModel):
    device_id: int = Field(description="Device ID")
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


class GetDeviceQueuesParams(ForbidExtraModel):
    device_id: int = Field(description="Device ID")


class GetDeviceInventoryParams(ForbidExtraModel):
    org_uuid: UUID = Field(description="Organization UUID")
    device_uuid: UUID = Field(description="Device UUID")
    category: str | None = Field(None, description="Filter by inventory category")


class GetDeviceInventoryCategoriesParams(ForbidExtraModel):
    org_uuid: UUID = Field(description="Organization UUID")
    device_uuid: UUID = Field(description="Device UUID")


# ============================================================================
# POLICY ENDPOINT SCHEMAS
# ============================================================================


class ListPoliciesConfigParams(ForbidExtraModel):
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


class GetPolicyParams(ForbidExtraModel):
    policy_id: int = Field(description="Policy ID")


class GetPolicyStatsParams(ForbidExtraModel):
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
# USER ENDPOINT SCHEMAS
# ============================================================================


class ListUsersParams(ForbidExtraModel):
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


class GetUserParams(ForbidExtraModel):
    user_id: int = Field(description="User ID")


# ============================================================================
# REPORT ENDPOINT SCHEMAS
# ============================================================================


class GetPrepatchReportParams(ForbidExtraModel):
    group_id: int | None = Field(None, description="Filter by Server Group ID")
    limit: int | None = Field(None, ge=1, description="Maximum number of results")
    offset: int | None = Field(None, ge=0, description="Offset for pagination")


class GetNeedsAttentionReportParams(ForbidExtraModel):
    group_id: int | None = Field(None, description="Filter by Server Group ID")
    limit: int | None = Field(None, ge=1, description="Maximum number of results")
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
    event_name: str | None = Field(None, description="Filter by event name")
    start_date: str | None = Field(None, description="Start date filter (ISO format)")
    end_date: str | None = Field(None, description="End date filter (ISO format)")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


# ============================================================================
# ORGANIZATION ENDPOINT SCHEMAS
# ============================================================================


class ListOrganizationsParams(ForbidExtraModel):
    page: int | None = Field(None, ge=0, description="Page number")
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


class UpdateDeviceParams(ForbidExtraModel):
    device_id: int = Field(description="Device ID")
    server_group_id: int = Field(description="Server group ID to assign device to")
    exception: bool = Field(description="Mark device as exception")
    ip_addrs: list | None = Field(None, description="IP addresses")
    tags: list | None = Field(None, description="Device tags")
    custom_name: str | None = Field(None, description="Custom device name")


class BatchUpdateDevicesParams(ForbidExtraModel):
    devices: list = Field(description="List of device IDs")
    actions: list = Field(description="List of actions to perform")


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
        None, description="Comma-separated patch names (required for patch_specific command)"
    )


class ClonePolicyParams(ForbidExtraModel):
    policy_id: int = Field(description="Policy ID to clone")
    target_zone_ids: list = Field(description="List of target zone IDs")


class PreviewPolicyDeviceFiltersParams(ForbidExtraModel):
    device_filters: list | None = Field(None, description="Device filter criteria")
    server_groups: list | None = Field(None, description="Server group IDs")
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


class CreateServerGroupParams(ForbidExtraModel):
    name: str = Field(description="Group name")
    refresh_interval: int = Field(description="Refresh interval in minutes")
    parent_server_group_id: int | None = Field(None, description="Parent group ID")
    ui_color: str | None = Field(None, description="UI color for group")
    notes: str | None = Field(None, description="Group notes")
    policies: list | None = Field(None, description="Policy IDs to assign")


class UpdateServerGroupParams(ForbidExtraModel):
    group_id: int = Field(description="Server group ID")
    name: str = Field(description="Group name")
    refresh_interval: int = Field(description="Refresh interval in minutes")
    parent_server_group_id: int | None = Field(None, description="Parent group ID")
    ui_color: str | None = Field(None, description="UI color for group")
    notes: str | None = Field(None, description="Group notes")
    policies: list | None = Field(None, description="Policy IDs to assign")


class UpdateApprovalParams(ForbidExtraModel):
    approval_id: int = Field(description="Approval ID")
    status: str = Field(description="Status: approved or rejected")
    notes: str | None = Field(None, description="Approval notes")


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


class ListZonesParams(AccountIdMixin, ForbidExtraModel):
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


# ------------------------------------------------------------------------
# DELETE Operation Params
# ------------------------------------------------------------------------


class DeleteDeviceParams(OrgIdRequiredMixin, ForbidExtraModel):
    device_id: int = Field(description="Device/Server ID to delete")


class DeleteServerGroupParams(OrgIdRequiredMixin, ForbidExtraModel):
    group_id: int = Field(description="Server group ID to delete")


class DeletePolicyParams(OrgIdRequiredMixin, ForbidExtraModel):
    policy_id: int = Field(description="Policy ID to delete")


class DeleteUserApiKeyParams(ForbidExtraModel):
    user_id: int = Field(description="User ID")
    api_key_id: int = Field(description="API key ID to delete")


class RemoveUserFromAccountParams(ForbidExtraModel):
    account_id: UUID = Field(description="Account ID (UUID)")
    user_id: UUID = Field(description="User UUID to remove from account")


class DeleteActionSetParams(OrgIdRequiredMixin, ForbidExtraModel):
    action_set_id: int = Field(description="Action set ID to delete")


class BulkDeleteActionSetsParams(OrgIdRequiredMixin, ForbidExtraModel):
    action_set_ids: list = Field(description="List of action set IDs to delete")


class DeleteGlobalApiKeyParams(ForbidExtraModel):
    key_id: str = Field(description="Global API key ID to delete")


# ------------------------------------------------------------------------
# Additional GET Operation Params
# ------------------------------------------------------------------------


class GetAccountParams(AccountIdMixin, ForbidExtraModel):
    pass


class ListAccountRbacRolesParams(AccountIdMixin, ForbidExtraModel):
    pass


class GetAccountUserParams(AccountIdMixin, ForbidExtraModel):
    user_id: str = Field(description="User UUID")


class GetUserZonesParams(AccountIdMixin, ForbidExtraModel):
    user_id: str = Field(description="User UUID")


class GetZoneParams(AccountIdMixin, ForbidExtraModel):
    zone_id: str = Field(description="Zone ID (UUID)")


class GetZoneUsersParams(AccountIdMixin, ForbidExtraModel):
    zone_id: str = Field(description="Zone ID (UUID)")


class ListApprovalsParams(OrgIdRequiredMixin, ForbidExtraModel):
    page: int | None = Field(None, ge=0, description="Page number")
    limit: int | None = Field(None, ge=1, le=500, description="Results per page")


class ListDataExtractsParams(OrgIdRequiredMixin, ForbidExtraModel):
    pass


class GetDataExtractParams(OrgIdRequiredMixin, ForbidExtraModel):
    extract_id: str = Field(description="Data extract ID")


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


class ListUserApiKeysParams(ForbidExtraModel):
    user_id: int = Field(description="User ID")


class GetUserApiKeyParams(ForbidExtraModel):
    user_id: int = Field(description="User ID")
    api_key_id: int = Field(description="API key ID")


class SearchWisParams(OrgIdRequiredMixin, ForbidExtraModel):
    query: str | None = Field(None, description="Search query")


class GetWisItemParams(OrgIdRequiredMixin, ForbidExtraModel):
    item_id: str = Field(description="WIS item ID")


# ------------------------------------------------------------------------
# Additional POST Operation Params
# ------------------------------------------------------------------------


class CreateZoneParams(AccountIdMixin, ForbidExtraModel):
    zone_data: dict = Field(description="Zone configuration data")


class CreateDataExtractParams(OrgIdRequiredMixin, ForbidExtraModel):
    extract_data: dict = Field(description="Data extract configuration")


class CreateGlobalApiKeyParams(ForbidExtraModel):
    key_data: dict = Field(description="API key configuration")


class DecryptGlobalApiKeyParams(ForbidExtraModel):
    key_id: str = Field(description="Global API key ID to decrypt")


class UploadActionSetParams(OrgIdRequiredMixin, ForbidExtraModel):
    action_set_data: dict = Field(description="Action set upload data")


class AddActionToActionSetParams(OrgIdRequiredMixin, ForbidExtraModel):
    action_set_id: int = Field(description="Action set ID")
    action_data: dict = Field(description="Action configuration")


class UploadPolicyFilesParams(OrgIdRequiredMixin, ForbidExtraModel):
    policy_id: int = Field(description="Policy ID")
    file_data: dict = Field(description="File upload data")


class AddDeviceQueueCommandParams(OrgIdRequiredMixin, ForbidExtraModel):
    device_id: int = Field(description="Device ID")
    command_data: dict = Field(description="Command configuration")


class CreateUserApiKeyParams(ForbidExtraModel):
    user_id: int = Field(description="User ID")
    key_data: dict = Field(description="API key configuration")


class DecryptUserApiKeyParams(ForbidExtraModel):
    user_id: int = Field(description="User ID")
    api_key_id: int = Field(description="API key ID to decrypt")


# ------------------------------------------------------------------------
# Additional PUT/PATCH Operation Params
# ------------------------------------------------------------------------


class UpdateGlobalApiKeyParams(ForbidExtraModel):
    key_id: str = Field(description="Global API key ID")
    key_data: dict = Field(description="Updated API key configuration")


class PatchUserParams(OrgIdRequiredMixin, ForbidExtraModel):
    user_id: int = Field(description="User ID")
    user_data: dict = Field(description="Partial user update data")


class UpdateUserApiKeyParams(ForbidExtraModel):
    user_id: int = Field(description="User ID")
    api_key_id: int = Field(description="API key ID")
    key_data: dict = Field(description="Updated API key configuration")


class MCPError(BaseModel):
    code: str | None
    message: str
    status: int


class ToolResult(BaseModel):
    response: ToolResponse
    deprecated_endpoint: bool = Field(
        True, description="Whether Automox notes this endpoint as deprecated"
    )

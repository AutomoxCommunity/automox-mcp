"""Tests for Pydantic schema validation boundaries in automox_mcp.schemas."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from automox_mcp.schemas import (
    AdvancedDeviceSearchParams,
    AssignPoliciesToSavedSearchParams,
    CreateDataExtractParams,
    CreatePolicyOperation,
    CreateSavedSearchParams,
    DeviceSearchParams,
    ForbidExtraModel,
    InviteUserParams,
    IssueDeviceCommandParams,
    PolicyChangeRequestParams,
    PolicyDefinition,
    UpdatePolicyOperation,
    UpdateSavedSearchParams,
    UploadActionSetParams,
)

# ---------------------------------------------------------------------------
# ForbidExtraModel — extra fields rejected
# ---------------------------------------------------------------------------


class TestForbidExtraModel:
    def test_rejects_unknown_fields(self):
        class MyModel(ForbidExtraModel):
            name: str

        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            MyModel(name="ok", unknown_field="bad")

    def test_accepts_known_fields(self):
        class MyModel(ForbidExtraModel):
            name: str

        m = MyModel(name="ok")
        assert m.name == "ok"


# ---------------------------------------------------------------------------
# PolicyDefinition — extra="ignore" silently drops unknown fields
# ---------------------------------------------------------------------------


class TestPolicyDefinition:
    def test_ignores_unknown_fields(self):
        p = PolicyDefinition(name="Test", unrecognized_key="dropped")
        assert p.name == "Test"
        assert not hasattr(p, "unrecognized_key")

    def test_schedule_time_valid_format(self):
        p = PolicyDefinition(schedule_time="14:30")
        assert p.schedule_time == "14:30"

    def test_schedule_time_invalid_format(self):
        with pytest.raises(ValidationError, match="schedule_time"):
            PolicyDefinition(schedule_time="25:00")

    def test_schedule_time_no_seconds(self):
        with pytest.raises(ValidationError, match="schedule_time"):
            PolicyDefinition(schedule_time="14:30:00")

    def test_scheduled_timezone_valid(self):
        p = PolicyDefinition(scheduled_timezone="UTC+0530")
        assert p.scheduled_timezone == "UTC+0530"

    def test_scheduled_timezone_invalid(self):
        with pytest.raises(ValidationError):
            PolicyDefinition(scheduled_timezone="EST")

    def test_schedule_days_bitmask_range(self):
        p = PolicyDefinition(schedule_days=254)
        assert p.schedule_days == 254

    def test_schedule_days_bitmask_too_large(self):
        with pytest.raises(ValidationError):
            PolicyDefinition(schedule_days=255)


# ---------------------------------------------------------------------------
# InviteUserParams — model_validator for zone assignments
# ---------------------------------------------------------------------------

_VALID_ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000001")


class TestInviteUserParams:
    def test_global_admin_no_zones_ok(self):
        p = InviteUserParams(
            account_id=_VALID_ACCOUNT_ID,
            email="user@example.com",
            account_rbac_role="global-admin",
        )
        assert p.zone_assignments is None

    def test_no_global_access_requires_zones(self):
        with pytest.raises(ValidationError, match="Zone assignments are required"):
            InviteUserParams(
                account_id=_VALID_ACCOUNT_ID,
                email="user@example.com",
                account_rbac_role="no-global-access",
            )

    def test_no_global_access_with_zones_ok(self):
        p = InviteUserParams(
            account_id=_VALID_ACCOUNT_ID,
            email="user@example.com",
            account_rbac_role="no-global-access",
            zone_assignments=[{"zone_id": "zone-1", "rbac_role": "read-only"}],
        )
        assert len(p.zone_assignments) == 1

    def test_invalid_email_rejected(self):
        with pytest.raises(ValidationError, match="email"):
            InviteUserParams(
                account_id=_VALID_ACCOUNT_ID,
                email="not-an-email",
                account_rbac_role="global-admin",
            )

    def test_invalid_rbac_role_rejected(self):
        with pytest.raises(ValidationError):
            InviteUserParams(
                account_id=_VALID_ACCOUNT_ID,
                email="user@example.com",
                account_rbac_role="superadmin",
            )


# ---------------------------------------------------------------------------
# CreateDataExtractParams — payload size validator
# ---------------------------------------------------------------------------


class TestCreateDataExtractParams:
    def test_small_payload_accepted(self):
        p = CreateDataExtractParams(org_id=1, extract_data={"type": "devices"})
        assert p.extract_data["type"] == "devices"

    def test_oversized_payload_rejected(self):
        huge = {"data": "x" * 60_000}
        with pytest.raises(ValidationError, match="50 KB"):
            CreateDataExtractParams(org_id=1, extract_data=huge)


# ---------------------------------------------------------------------------
# UploadActionSetParams — payload size validator
# ---------------------------------------------------------------------------


class TestUploadActionSetParams:
    def test_small_payload_accepted(self):
        p = UploadActionSetParams(org_id=1, action_set_data={"format": "qualys"})
        assert p.action_set_data["format"] == "qualys"

    def test_oversized_payload_rejected(self):
        huge = {"data": "x" * 60_000}
        with pytest.raises(ValidationError, match="50 KB"):
            UploadActionSetParams(org_id=1, action_set_data=huge)


# ---------------------------------------------------------------------------
# AdvancedDeviceSearchParams — query size validator
# ---------------------------------------------------------------------------


class TestAdvancedDeviceSearchParams:
    def test_no_query_ok(self):
        p = AdvancedDeviceSearchParams()
        assert p.query is None

    def test_small_query_accepted(self):
        p = AdvancedDeviceSearchParams(query={"filter": "os=linux"})
        assert p.query["filter"] == "os=linux"

    def test_oversized_query_rejected(self):
        huge = {"filter": "x" * 60_000}
        with pytest.raises(ValidationError, match="50 KB"):
            AdvancedDeviceSearchParams(query=huge)


# ---------------------------------------------------------------------------
# Saved-search CRUD schemas
# ---------------------------------------------------------------------------


class TestCreateSavedSearchParams:
    def test_minimal_fields_accepted(self):
        p = CreateSavedSearchParams(name="x", query={"k": "v"})
        assert p.description is None

    def test_oversized_query_rejected(self):
        huge = {"filter": "x" * 60_000}
        with pytest.raises(ValidationError, match="50 KB"):
            CreateSavedSearchParams(name="x", query=huge)

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            CreateSavedSearchParams(name="", query={"k": "v"})


class TestUpdateSavedSearchParams:
    def test_requires_at_least_one_field(self):
        with pytest.raises(ValidationError, match="at least one"):
            UpdateSavedSearchParams(saved_search_id="ss-1")

    def test_name_only_accepted(self):
        p = UpdateSavedSearchParams(saved_search_id="ss-1", name="renamed")
        assert p.name == "renamed"

    def test_oversized_query_rejected(self):
        huge = {"filter": "x" * 60_000}
        with pytest.raises(ValidationError, match="50 KB"):
            UpdateSavedSearchParams(saved_search_id="ss-1", query=huge)


class TestAssignPoliciesToSavedSearchParams:
    def test_requires_non_empty_policy_ids(self):
        with pytest.raises(ValidationError):
            AssignPoliciesToSavedSearchParams(
                saved_search_uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                policy_ids=[],
            )

    def test_accepts_uuid_string(self):
        p = AssignPoliciesToSavedSearchParams(
            saved_search_uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            policy_ids=[1, 2],
        )
        assert p.policy_ids == [1, 2]


# ---------------------------------------------------------------------------
# Splashtop schemas
# ---------------------------------------------------------------------------


class TestSplashtopInstallParams:
    def test_minimal_accepted(self):
        from automox_mcp.schemas import SplashtopInstallParams

        p = SplashtopInstallParams(
            device_uuid="550e8400-e29b-41d4-a716-446655440000",
            os_family="windows",
        )
        assert p.request_permission is None

    def test_rejects_unknown_os_family(self):
        from automox_mcp.schemas import SplashtopInstallParams

        with pytest.raises(ValidationError, match="os_family"):
            SplashtopInstallParams(
                device_uuid="550e8400-e29b-41d4-a716-446655440000",
                os_family="solaris",
            )

    def test_rejects_unknown_request_permission(self):
        from automox_mcp.schemas import SplashtopInstallParams

        with pytest.raises(ValidationError, match="request_permission"):
            SplashtopInstallParams(
                device_uuid="550e8400-e29b-41d4-a716-446655440000",
                os_family="windows",
                request_permission="silent_force",
            )


class TestSplashtopInitiateConnectionParams:
    def test_accepts_remote_control(self):
        from automox_mcp.schemas import SplashtopInitiateConnectionParams

        p = SplashtopInitiateConnectionParams(
            device_uuid="550e8400-e29b-41d4-a716-446655440000",
            os_family="windows",
            connection_type="remote_control",
        )
        assert p.connection_type == "remote_control"

    def test_rejects_unknown_connection_type(self):
        from automox_mcp.schemas import SplashtopInitiateConnectionParams

        with pytest.raises(ValidationError, match="connection_type"):
            SplashtopInitiateConnectionParams(
                device_uuid="550e8400-e29b-41d4-a716-446655440000",
                os_family="windows",
                connection_type="screen_share",
            )


class TestSplashtopBulkActionParams:
    def test_accepts_install(self):
        from automox_mcp.schemas import SplashtopBulkActionParams

        p = SplashtopBulkActionParams(action="install", server_group_id=1)
        assert p.action == "install"

    def test_rejects_unknown_action(self):
        from automox_mcp.schemas import SplashtopBulkActionParams

        with pytest.raises(ValidationError, match="action"):
            SplashtopBulkActionParams(action="reboot")


class TestSplashtopSetBulkAttendedAccessParams:
    def test_requires_non_empty_device_uuids(self):
        from automox_mcp.schemas import SplashtopSetBulkAttendedAccessParams

        with pytest.raises(ValidationError):
            SplashtopSetBulkAttendedAccessParams(
                device_uuids=[],
                required_attended_access=True,
            )

    def test_accepts_one_uuid(self):
        from automox_mcp.schemas import SplashtopSetBulkAttendedAccessParams

        p = SplashtopSetBulkAttendedAccessParams(
            device_uuids=["550e8400-e29b-41d4-a716-446655440000"],
            required_attended_access=False,
        )
        assert p.required_attended_access is False


# ---------------------------------------------------------------------------
# PolicyChangeRequestParams — discriminated union
# ---------------------------------------------------------------------------


class TestPolicyChangeRequestParams:
    def test_create_operation_parsed(self):
        p = PolicyChangeRequestParams(
            org_id=42,
            operations=[
                {"action": "create", "policy": {"name": "New Policy"}},
            ],
        )
        assert len(p.operations) == 1
        assert isinstance(p.operations[0], CreatePolicyOperation)

    def test_update_operation_parsed(self):
        p = PolicyChangeRequestParams(
            org_id=42,
            operations=[
                {
                    "action": "update",
                    "policy_id": 123,
                    "policy": {"name": "Updated"},
                },
            ],
        )
        assert isinstance(p.operations[0], UpdatePolicyOperation)

    def test_empty_operations_rejected(self):
        with pytest.raises(ValidationError, match="operations"):
            PolicyChangeRequestParams(org_id=42, operations=[])

    def test_too_many_operations_rejected(self):
        ops = [{"action": "create", "policy": {"name": f"p{i}"}} for i in range(51)]
        with pytest.raises(ValidationError):
            PolicyChangeRequestParams(org_id=42, operations=ops)


# ---------------------------------------------------------------------------
# IssueDeviceCommandParams — command_type and patch_names validation
# ---------------------------------------------------------------------------


class TestIssueDeviceCommandParams:
    def test_scan_command_accepted(self):
        p = IssueDeviceCommandParams(org_id=1, device_id=10, command_type="scan")
        assert p.command_type == "scan"

    def test_invalid_command_rejected(self):
        with pytest.raises(ValidationError):
            IssueDeviceCommandParams(org_id=1, device_id=10, command_type="format")

    def test_patch_names_valid_chars(self):
        p = IssueDeviceCommandParams(
            org_id=1,
            device_id=10,
            command_type="patch_specific",
            patch_names="KB12345,Chrome Update",
        )
        assert "KB12345" in p.patch_names

    def test_patch_names_rejects_shell_chars(self):
        with pytest.raises(ValidationError, match="patch_names"):
            IssueDeviceCommandParams(
                org_id=1,
                device_id=10,
                command_type="patch_specific",
                patch_names="$(whoami)",
            )


# ---------------------------------------------------------------------------
# DeviceSearchParams — field constraints
# ---------------------------------------------------------------------------


class TestDeviceSearchParams:
    def test_limit_lower_bound(self):
        p = DeviceSearchParams(org_id=1, limit=1)
        assert p.limit == 1

    def test_limit_upper_bound(self):
        p = DeviceSearchParams(org_id=1, limit=500)
        assert p.limit == 500

    def test_limit_exceeds_max(self):
        with pytest.raises(ValidationError):
            DeviceSearchParams(org_id=1, limit=501)

    def test_limit_zero_rejected(self):
        with pytest.raises(ValidationError):
            DeviceSearchParams(org_id=1, limit=0)

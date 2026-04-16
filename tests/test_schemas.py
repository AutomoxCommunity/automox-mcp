"""Tests for Pydantic schema validation boundaries in automox_mcp.schemas."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from automox_mcp.schemas import (
    AdvancedDeviceSearchParams,
    CreateDataExtractParams,
    CreatePolicyOperation,
    DeviceSearchParams,
    ForbidExtraModel,
    InviteUserParams,
    IssueDeviceCommandParams,
    PolicyChangeRequestParams,
    PolicyDefinition,
    UpdatePolicyOperation,
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

"""Prompt: Prepare for Patch Tuesday."""

from __future__ import annotations

from fastmcp import FastMCP


def register(server: FastMCP) -> None:
    @server.prompt(
        name="prepare_patch_tuesday",
        description="Guided workflow to assess readiness and prepare for Microsoft Patch Tuesday.",
    )
    def prepare_patch_tuesday() -> str:
        return """Prepare for Patch Tuesday. Follow these steps:

1. **Get Patch Tuesday readiness**: Use `get_patch_tuesday_readiness` to get a combined view of pre-patch status, pending approvals, and policy schedules.

2. **Review pending approvals**: Use `patch_approvals_summary` to see all pending patch approval requests. Prioritize by severity (critical > high > medium > low).

3. **Check pre-patch report**: Use `prepatch_report` to identify devices with pending patches and their severity breakdown.

4. **Review patch policies**: Use `policy_catalog` to list all patch policies. For each active patch policy, use `policy_detail` to check:
   - Schedule (is it aligned with the Patch Tuesday window?)
   - Target groups (are all groups covered?)
   - Configuration (are critical patches auto-approved?)

5. **Identify at-risk devices**: Use `devices_needing_attention` to find devices that may need manual intervention before the patch window.

6. **Check fleet health**: Use `device_health_metrics` to get aggregate statistics on device connectivity and patch status.

7. **Approve pending patches**: For each pending approval, use `decide_patch_approval` to approve or reject based on severity and testing status.

8. **Verify schedules**: Ensure patch policies are scheduled to run during the appropriate maintenance window. If adjustments are needed, use `apply_policy_changes` to update schedules.

Present a summary report with:
- Total devices requiring patches (by severity)
- Pending approvals status
- Policy schedule overview
- At-risk devices requiring manual attention
- Recommended actions before the patch window"""

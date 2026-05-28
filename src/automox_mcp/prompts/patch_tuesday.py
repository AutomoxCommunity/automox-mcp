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

   - The tool accepts an optional `detail_limit` (default `10`) that caps every inner list (`prepatch_report.devices`, `patch_approvals.approvals`, `patch_policy_schedules`). Counts and aggregates (`total_devices_needing_patches`, `pending_count`, `readiness_summary`) are always returned in full, so set `detail_limit=0` if you only need the headline numbers.
   - If a section was truncated, the response surfaces `metadata.section_summaries.<key>` with `total`, `returned`, `has_more`, and a `follow_up_tool` + `follow_up_args_hint` pointing at the detail tool to call for the rest (`prepatch_report` for devices, `patch_approvals_summary` for approvals, `policy_catalog` for schedules). Use those hints rather than guessing at args.

2. **Review pending approvals**: Use `patch_approvals_summary` to see all pending patch approval requests. Prioritize by severity (critical > high > medium > low). Use this if step 1 reported truncated `patch_approvals.approvals` via `metadata.section_summaries`.

3. **Check pre-patch report**: Use `prepatch_report` to identify devices with pending patches and their severity breakdown. Use this if step 1 reported truncated `prepatch_report.devices`.

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

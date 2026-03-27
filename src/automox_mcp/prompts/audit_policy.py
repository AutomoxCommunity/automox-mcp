"""Prompt: Audit a policy's execution history."""

from __future__ import annotations

from fastmcp import FastMCP


def register(server: FastMCP) -> None:
    @server.prompt(
        name="audit_policy_execution",
        description="Guided workflow to audit a policy's execution history and identify issues.",
    )
    def audit_policy_execution(policy_id: str) -> str:
        return f"""Audit the execution history for policy {policy_id}. Follow these steps:

1. **Get policy details**: Use `policy_detail` with policy_id={policy_id} to understand the policy's configuration, schedule, and target groups.

2. **Review execution timeline**: Use `policy_execution_timeline` with the policy's UUID to see recent executions over the past 30 days. Look for patterns in success/failure rates.

3. **Check Policy History v2**: Use `policy_runs_v2` with policy_uuid filter to get richer execution data including device counts and time-range filtering.

4. **Get run counts**: Use `policy_run_count` to understand the overall execution volume.

5. **Examine failed runs**: For any runs with failures, use `policy_run_results` or `policy_run_detail_v2` to see per-device results. Identify:
   - Which devices consistently fail
   - Common error patterns
   - Whether failures are increasing or decreasing over time

6. **Check compliance stats**: Use `policy_compliance_stats` to see the overall compliance rate for this policy.

7. **Cross-reference with device health**: For consistently failing devices, use `device_detail` to check if the devices are online, reachable, and properly configured.

8. **Review audit trail**: Use `audit_events_ocsf` or `audit_trail_user_activity` to check if the policy was recently modified.

Present an audit report with:
- Policy configuration summary
- Execution frequency and success rate (last 7/14/30 days)
- Top failing devices and their error patterns
- Compliance trend
- Recommended actions to improve success rate"""

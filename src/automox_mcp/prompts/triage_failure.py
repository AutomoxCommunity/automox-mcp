"""Prompt: Triage a failed policy run."""

from __future__ import annotations

from fastmcp import FastMCP


def register(server: FastMCP) -> None:
    @server.prompt(
        name="triage_failed_policy_run",
        description="Guided workflow to triage and remediate a failed policy execution.",
    )
    def triage_failed_policy_run(policy_id: str) -> str:
        return f"""Triage the most recent failed policy run for policy {policy_id}. Follow these steps:

1. **Get policy details**: Use `policy_detail` with policy_id={policy_id} and include_recent_runs=10 to see the policy configuration and recent execution history.

2. **Identify the failed run**: From the recent runs, find the most recent run with failures. Note the execution token/UUID.

3. **Get per-device results**: Use `policy_run_results` with the failed run's execution details to see which devices failed and why.

4. **Categorize failures**: Group failures by error type:
   - **Timeout**: Device didn't respond within the execution window
   - **Script error**: The policy script/configuration has a bug
   - **Dependency missing**: Required software or configuration not present
   - **Permission denied**: Agent lacks required privileges
   - **Device offline**: Device was unreachable during execution

5. **Investigate top failures**: For the most common failure type, use `device_detail` on 2-3 affected devices to check:
   - Device connectivity (last_seen timestamp)
   - OS version and compatibility
   - Agent version
   - Pending commands in queue

6. **Check if failure is recurring**: Use `policy_execution_timeline` to see if these same devices have been failing consistently.

7. **Remediate**:
   - For offline devices: Use `execute_device_command` with command_type="scan" to refresh
   - For script errors: Review the policy configuration and use `apply_policy_changes` to fix
   - For stuck devices: Use `execute_device_command` with command_type="reboot" if appropriate
   - Re-run the policy: Use `execute_policy_now` to retry

8. **Set up monitoring**: Use `create_webhook` to set up notifications for future policy failures if not already configured.

Present a triage report with:
- Failure summary (device count, error types)
- Root cause analysis
- Actions taken
- Recommendations to prevent recurrence"""

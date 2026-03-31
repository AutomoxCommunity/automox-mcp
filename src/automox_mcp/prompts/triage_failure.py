"""Prompt: Triage a failed policy run."""

from __future__ import annotations

from fastmcp import FastMCP


def register(server: FastMCP) -> None:
    @server.prompt(
        name="triage_failed_policy_run",
        description="Guided workflow to triage and remediate a failed policy execution.",
    )
    def triage_failed_policy_run(policy_id: str) -> str:
        # Validate policy_id is a numeric identifier
        _safe_id = "".join(c for c in str(policy_id).strip() if c.isdigit())
        if not _safe_id or _safe_id != str(policy_id).strip():
            return "Error: policy_id must be a numeric identifier (e.g., '12345')."
        return f"""Triage the most recent failed policy run for policy {_safe_id}. Follow these steps:

1. **Get policy details**: Use `policy_detail` with policy_id={_safe_id} and include_recent_runs=10 to see the policy configuration and recent execution history.

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

7. **Propose remediation** (IMPORTANT: present the plan and wait for user confirmation before executing any commands):
   - For offline devices: Propose `execute_device_command` with command_type="scan" to refresh
   - For script errors: Propose reviewing the policy configuration and using `apply_policy_changes` to fix
   - For stuck devices: Propose `execute_device_command` with command_type="reboot" ONLY with explicit user approval
   - Re-run the policy: Propose `execute_policy_now` to retry
   **Ask the user to confirm before executing any remediation commands, especially reboots.**

8. **Set up monitoring**: Use `create_webhook` to set up notifications for future policy failures if not already configured.

Present a triage report with:
- Failure summary (device count, error types)
- Root cause analysis
- Actions taken
- Recommendations to prevent recurrence"""

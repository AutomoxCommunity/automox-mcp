"""Prompt: Investigate a non-compliant device."""

from __future__ import annotations

from fastmcp import FastMCP


def register(server: FastMCP) -> None:
    @server.prompt(
        name="investigate_noncompliant_device",
        description="Guided workflow to investigate why a device is non-compliant and remediate it.",
    )
    def investigate_noncompliant_device(device_id: str) -> str:
        # Validate device_id is a numeric identifier
        _safe_id = "".join(c for c in str(device_id).strip() if c.isdigit())
        if not _safe_id or _safe_id != str(device_id).strip():
            return "Error: device_id must be a numeric identifier (e.g., '12345')."
        return f"""Investigate non-compliant device {_safe_id}. Follow these steps:

1. **Get device details**: Use `device_detail` with device_id={_safe_id} to understand the device's current state, OS, and group membership.

2. **Check device inventory**: Use `get_device_inventory` to review hardware, security, and system details.

3. **Review installed packages**: Use `list_device_packages` to see which packages are present, their versions, and install state. Each entry has an `installed` boolean (true = installed, false = available but not installed) and a `severity` (risk: "critical"/"high"/"medium"/"low"/"no_known_cves" or null) — install state comes from `installed`, not from any patch-status field. Look for not-yet-installed packages (`installed`: false) with severity "critical" or "high".

4. **Check policy status**: From the device detail, identify which policies apply to this device and their compliance status.

5. **Review policy execution history**: For any failing policies, use `policy_execution_timeline` to see recent runs and `policy_run_results` to understand per-device failures.

6. **Determine root cause**: Based on the above, identify whether the non-compliance is due to:
   - Missing patches (check packages with `installed`: false — available but not yet installed — prioritizing high/critical `severity`)
   - Failed policy execution (check policy run results for errors)
   - Device offline/stale (check last_seen timestamp)
   - Configuration drift (compare device state to policy requirements)

7. **Propose remediation** (IMPORTANT: present the plan and wait for user confirmation before executing any commands):
   - For missing patches: Propose using `execute_device_command` with command_type="patch_all"
   - For stale devices: Propose using `execute_device_command` with command_type="scan" to refresh state
   - For policy failures: Propose using `execute_policy_now` to re-run the failing policy
   **Ask the user to confirm before executing any remediation commands.**

8. **Verify**: After user-approved remediation, use `device_detail` again to confirm the device is now compliant.

Report your findings and actions taken in a clear summary."""

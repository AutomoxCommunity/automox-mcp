"""Prompt: Review fleet security posture."""

from __future__ import annotations

from fastmcp import FastMCP


def register(server: FastMCP) -> None:
    @server.prompt(
        name="review_security_posture",
        description="Guided workflow to review and assess the organization's fleet security posture.",
    )
    def review_security_posture() -> str:
        return """Review the fleet security posture. Follow these steps:

1. **Get compliance snapshot**: Use `get_compliance_snapshot` for a combined view of non-compliant devices, health metrics, and policy compliance statistics.

2. **Check fleet health**: Use `device_health_metrics` for aggregate statistics on device connectivity, patch status, and OS distribution.

3. **Identify non-compliant devices**: Use `noncompliant_report` to get a detailed list of devices failing policy checks. Sort by severity.

4. **Review critical patches**: Use `search_org_packages` with severity filtering to find critical and high-severity patches across the organization.

5. **Check vulnerability remediation**: Use `list_remediation_action_sets` to see if there are pending vulnerability remediation workflows.

6. **Review policy health**: Use `policy_health_overview` to see which policies are succeeding and which have recent failures.

7. **Check pending approvals**: Use `patch_approvals_summary` to identify any critical patches waiting for approval.

8. **Audit recent changes**: Use `audit_events_ocsf` with today's date to review recent administrative actions that may affect security posture.

9. **Review devices needing attention**: Use `devices_needing_attention` to surface devices flagged for immediate action.

Present a security posture report with:
- Fleet compliance rate (% of devices compliant)
- Critical findings (devices with critical/high vulnerabilities)
- Patch coverage (% of patches installed across fleet)
- Policy health (success rates for security-related policies)
- Device connectivity (% of devices reporting in last 24/48/72 hours)
- Pending approvals and remediation actions
- Top 5 recommended actions to improve posture"""

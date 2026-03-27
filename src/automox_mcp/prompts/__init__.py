"""Workflow prompts for guided multi-step admin tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_prompts(server: FastMCP) -> None:
    """Register all workflow prompts with the server."""
    from .audit_policy import register as register_audit_policy
    from .investigate_device import register as register_investigate_device
    from .onboard_group import register as register_onboard_group
    from .patch_tuesday import register as register_patch_tuesday
    from .security_posture import register as register_security_posture
    from .triage_failure import register as register_triage_failure

    register_investigate_device(server)
    register_patch_tuesday(server)
    register_audit_policy(server)
    register_onboard_group(server)
    register_triage_failure(server)
    register_security_posture(server)


__all__ = ["register_prompts"]

"""Tests for workflow prompts."""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from automox_mcp.prompts import register_prompts


@pytest.fixture
def server() -> FastMCP:
    s = FastMCP("test")
    register_prompts(s)
    return s


def test_all_prompts_registered(server: FastMCP) -> None:
    """Verify all 6 prompts are registered."""
    pm = server._prompt_manager
    prompt_names = set(pm._prompts.keys())
    expected = {
        "investigate_noncompliant_device",
        "prepare_patch_tuesday",
        "audit_policy_execution",
        "onboard_device_group",
        "triage_failed_policy_run",
        "review_security_posture",
    }
    assert expected.issubset(prompt_names), f"Missing prompts: {expected - prompt_names}"


def test_prompt_count(server: FastMCP) -> None:
    pm = server._prompt_manager
    assert len(pm._prompts) == 6


def test_investigate_device_prompt_renders(server: FastMCP) -> None:
    pm = server._prompt_manager
    prompt = pm._prompts["investigate_noncompliant_device"]
    result = prompt.fn(device_id="12345")
    assert "12345" in result
    assert "device_detail" in result


def test_patch_tuesday_prompt_renders(server: FastMCP) -> None:
    pm = server._prompt_manager
    prompt = pm._prompts["prepare_patch_tuesday"]
    result = prompt.fn()
    assert "Patch Tuesday" in result
    assert "patch_approvals_summary" in result


def test_audit_policy_prompt_renders(server: FastMCP) -> None:
    pm = server._prompt_manager
    prompt = pm._prompts["audit_policy_execution"]
    result = prompt.fn(policy_id="999")
    assert "999" in result
    assert "policy_execution_timeline" in result


def test_onboard_group_prompt_renders(server: FastMCP) -> None:
    pm = server._prompt_manager
    prompt = pm._prompts["onboard_device_group"]
    result = prompt.fn(group_name="Production Servers")
    assert "Production Servers" in result
    assert "create_server_group" in result


def test_triage_failure_prompt_renders(server: FastMCP) -> None:
    pm = server._prompt_manager
    prompt = pm._prompts["triage_failed_policy_run"]
    result = prompt.fn(policy_id="555")
    assert "555" in result
    assert "policy_run_results" in result


def test_security_posture_prompt_renders(server: FastMCP) -> None:
    pm = server._prompt_manager
    prompt = pm._prompts["review_security_posture"]
    result = prompt.fn()
    assert "compliance" in result.lower()
    assert "device_health_metrics" in result

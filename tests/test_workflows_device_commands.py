"""Tests for automox_mcp.workflows.device_commands."""

from __future__ import annotations

from typing import cast

import pytest

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.device_commands import issue_device_command
from conftest import StubClient


@pytest.mark.asyncio
async def test_issue_device_command_scan():
    client = StubClient(post_responses={"/servers/": [{"status": "queued"}]})
    result = await issue_device_command(
        cast(AutomoxClient, client),
        device_id=100,
        command_type="scan",
    )

    assert result["data"]["command_type"] == "GetOS"
    assert result["data"]["device_id"] == 100
    assert result["data"]["command_queued"] is True
    assert result["metadata"]["org_id"] == 42
    assert result["metadata"]["device_id"] == 100


@pytest.mark.asyncio
async def test_issue_device_command_patch_all():
    client = StubClient(post_responses={"/servers/": [{}]})
    result = await issue_device_command(
        cast(AutomoxClient, client),
        device_id=200,
        command_type="patch_all",
    )

    assert result["data"]["command_type"] == "InstallAllUpdates"
    assert result["data"]["device_id"] == 200
    assert result["data"]["patch_names"] is None


@pytest.mark.asyncio
async def test_issue_device_command_patch_specific():
    client = StubClient(post_responses={"/servers/": [{}]})
    result = await issue_device_command(
        cast(AutomoxClient, client),
        device_id=300,
        command_type="patch_specific",
        patch_names="KB1234567,KB9999999",
    )

    assert result["data"]["command_type"] == "InstallUpdate"
    assert result["data"]["patch_names"] == "KB1234567,KB9999999"
    assert result["data"]["command_queued"] is True


@pytest.mark.asyncio
async def test_issue_device_command_reboot():
    client = StubClient(post_responses={"/servers/": [{}]})
    result = await issue_device_command(
        cast(AutomoxClient, client),
        device_id=400,
        command_type="reboot",
    )

    assert result["data"]["command_type"] == "Reboot"
    assert result["data"]["device_id"] == 400


@pytest.mark.asyncio
async def test_issue_device_command_invalid_command_raises():
    client = StubClient()
    with pytest.raises(ValueError, match="Invalid command"):
        await issue_device_command(
            cast(AutomoxClient, client),
            device_id=100,
            command_type="explode",
        )


@pytest.mark.asyncio
async def test_issue_device_command_patch_specific_missing_patch_names_raises():
    client = StubClient()
    with pytest.raises(ValueError, match="patch_names is required"):
        await issue_device_command(
            cast(AutomoxClient, client),
            device_id=100,
            command_type="patch_specific",
        )


@pytest.mark.asyncio
async def test_issue_device_command_missing_org_id_raises():
    client = StubClient()
    client.org_id = None
    with pytest.raises(ValueError, match="org_id required"):
        await issue_device_command(
            cast(AutomoxClient, client),
            device_id=100,
            command_type="scan",
        )


@pytest.mark.asyncio
async def test_issue_device_command_explicit_org_id_overrides_client():
    client = StubClient(post_responses={"/servers/": [{}]})
    client.org_id = None
    result = await issue_device_command(
        cast(AutomoxClient, client),
        org_id=99,
        device_id=500,
        command_type="scan",
    )

    assert result["metadata"]["org_id"] == 99

"""Tests for webhook URL validation — sync structural checks vs async DNS.

The split exists because Pydantic validators are sync; running DNS there used
to block the entire asyncio event loop for up to 5 s per call (S-1). The sync
validator must therefore NOT do DNS, and the async validator must catch
hostnames that resolve to private addresses.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from automox_mcp.tools.webhook_tools import (
    _validate_webhook_url_dns,
    _validate_webhook_url_sync,
)

# ---------------------------------------------------------------------------
# Sync validator — structural checks only, no DNS
# ---------------------------------------------------------------------------


def test_sync_validator_rejects_non_https():
    with pytest.raises(ValueError, match="HTTPS"):
        _validate_webhook_url_sync("http://example.com/hook")


def test_sync_validator_rejects_userinfo():
    with pytest.raises(ValueError, match="userinfo"):
        _validate_webhook_url_sync("https://user:pass@example.com/hook")


def test_sync_validator_rejects_bare_private_ip():
    with pytest.raises(ValueError, match="must not target"):
        _validate_webhook_url_sync("https://10.0.0.1/hook")


def test_sync_validator_rejects_loopback_ipv6():
    with pytest.raises(ValueError, match="must not target"):
        _validate_webhook_url_sync("https://[::1]/hook")


def test_sync_validator_rejects_link_local():
    with pytest.raises(ValueError, match="must not target"):
        _validate_webhook_url_sync("https://169.254.169.254/hook")


def test_sync_validator_rejects_cloud_metadata_hostname():
    with pytest.raises(ValueError, match="cloud metadata"):
        _validate_webhook_url_sync("https://metadata.google.internal/")


def test_sync_validator_rejects_dot_internal_suffix():
    with pytest.raises(ValueError, match="cloud metadata"):
        _validate_webhook_url_sync("https://anything.internal/x")


def test_sync_validator_returns_none_for_bare_public_ip():
    # 8.8.8.8 is public — no DNS lookup needed in the async pass.
    assert _validate_webhook_url_sync("https://8.8.8.8/hook") is None


def test_sync_validator_returns_hostname_for_resolvable_name():
    # Hostname is returned so the async pass can resolve and re-check the IP.
    assert _validate_webhook_url_sync("https://example.com/hook") == "example.com"


def test_sync_validator_does_not_call_dns():
    """Regression for S-1: the sync validator must NOT trigger socket.getaddrinfo.

    Any DNS call inside the Pydantic validator blocks the entire asyncio event
    loop. Patching ``socket.getaddrinfo`` to raise lets us assert the sync path
    never reaches it.
    """
    with patch("socket.getaddrinfo", side_effect=AssertionError("DNS called in sync path")):
        # All these should complete without touching DNS.
        assert _validate_webhook_url_sync("https://example.com/hook") == "example.com"
        assert _validate_webhook_url_sync("https://8.8.8.8/hook") is None


# ---------------------------------------------------------------------------
# Async DNS validator — SSRF defense against hostnames pointing at internal IPs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_validator_rejects_hostname_resolving_to_private_ip():
    """Hostname whose A record points at RFC1918 — must be rejected."""

    async def fake_getaddrinfo(*_args, **_kwargs):
        # Mimic the (family, type, proto, canonname, sockaddr) shape.
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.5", 0))]

    with patch("asyncio.get_event_loop") as get_loop:
        loop = get_loop.return_value
        loop.getaddrinfo = fake_getaddrinfo  # type: ignore[assignment]

        with pytest.raises(ValueError, match="private/internal"):
            await _validate_webhook_url_dns("https://evil.example/hook")


@pytest.mark.asyncio
async def test_async_validator_accepts_hostname_resolving_to_public_ip():
    async def fake_getaddrinfo(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]

    with patch("asyncio.get_event_loop") as get_loop:
        loop = get_loop.return_value
        loop.getaddrinfo = fake_getaddrinfo  # type: ignore[assignment]

        # Returns None on success — no exception.
        assert await _validate_webhook_url_dns("https://example.com/hook") is None


@pytest.mark.asyncio
async def test_async_validator_short_circuits_for_bare_public_ip():
    """Bare public IPs do not require DNS — the async pass returns without
    touching getaddrinfo, so it cannot block on DNS timeout either.
    """

    async def boom(*_args, **_kwargs):
        raise AssertionError("DNS called for bare public IP")

    with patch("asyncio.get_event_loop") as get_loop:
        loop = get_loop.return_value
        loop.getaddrinfo = boom  # type: ignore[assignment]

        await _validate_webhook_url_dns("https://8.8.8.8/hook")


@pytest.mark.asyncio
async def test_async_validator_rejects_unresolvable_hostname():
    async def fake_getaddrinfo(*_args, **_kwargs):
        raise socket.gaierror("no such host")

    with patch("asyncio.get_event_loop") as get_loop:
        loop = get_loop.return_value
        loop.getaddrinfo = fake_getaddrinfo  # type: ignore[assignment]

        with pytest.raises(ValueError, match="could not be resolved"):
            await _validate_webhook_url_dns("https://nx.invalid/hook")

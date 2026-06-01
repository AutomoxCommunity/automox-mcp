"""Tests for the local-file upload guard (utils/upload.py).

These cover the security-critical path validation for upload_policy_file:
allowlist enforcement, `..` traversal, symlink escape, type/size checks, and
the env-driven getters.
"""

from __future__ import annotations

import pytest

from automox_mcp.utils.upload import (
    get_upload_allowed_dirs,
    get_upload_max_bytes,
    get_upload_timeout_seconds,
    validate_upload_path,
)

_GB = 10 * 1024 * 1024 * 1024


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS",
        "AUTOMOX_MCP_UPLOAD_MAX_BYTES",
        "AUTOMOX_MCP_UPLOAD_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_no_allowlist_is_fail_closed(tmp_path, monkeypatch) -> None:
    f = tmp_path / "a.bin"
    f.write_bytes(b"x")
    with pytest.raises(ValueError, match="not configured"):
        validate_upload_path(str(f))


def test_file_inside_allowlist_ok(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS", str(tmp_path))
    f = tmp_path / "installer.pkg"
    f.write_bytes(b"payload")
    assert validate_upload_path(str(f)) == f.resolve()


def test_file_outside_allowlist_rejected(tmp_path, monkeypatch) -> None:
    allowed = tmp_path / "ok"
    allowed.mkdir()
    other = tmp_path / "secret"
    other.mkdir()
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS", str(allowed))
    f = other / "x.bin"
    f.write_bytes(b"x")
    with pytest.raises(ValueError, match="outside the allowed"):
        validate_upload_path(str(f))


def test_dotdot_traversal_rejected(tmp_path, monkeypatch) -> None:
    allowed = tmp_path / "ok"
    allowed.mkdir()
    secret = tmp_path / "secret.bin"
    secret.write_bytes(b"x")
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS", str(allowed))
    # An in-allowlist prefix that climbs out via `..`.
    sneaky = str(allowed / ".." / "secret.bin")
    with pytest.raises(ValueError, match="outside the allowed"):
        validate_upload_path(sneaky)


def test_symlink_escape_rejected(tmp_path, monkeypatch) -> None:
    allowed = tmp_path / "ok"
    allowed.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"x")
    link = allowed / "link.bin"
    link.symlink_to(outside)
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS", str(allowed))
    # The symlink lives inside the allowlist but resolves outside it.
    with pytest.raises(ValueError, match="outside the allowed"):
        validate_upload_path(str(link))


def test_missing_file_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS", str(tmp_path))
    with pytest.raises(ValueError, match="does not exist"):
        validate_upload_path(str(tmp_path / "nope.bin"))


def test_directory_rejected(tmp_path, monkeypatch) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS", str(tmp_path))
    with pytest.raises(ValueError, match="regular file"):
        validate_upload_path(str(sub))


def test_empty_file_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS", str(tmp_path))
    f = tmp_path / "empty.bin"
    f.touch()
    with pytest.raises(ValueError, match="empty"):
        validate_upload_path(str(f))


def test_oversized_file_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS", str(tmp_path))
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_MAX_BYTES", "4")
    f = tmp_path / "big.bin"
    f.write_bytes(b"12345")
    with pytest.raises(ValueError, match="exceeding"):
        validate_upload_path(str(f))


def test_getters_defaults() -> None:
    assert get_upload_allowed_dirs() == []
    assert get_upload_max_bytes() == _GB
    assert get_upload_timeout_seconds() == 3600.0


def test_allowlist_drops_nonexistent_entries(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS", f"{tmp_path}, ,/does/not/exist/xyz")
    assert get_upload_allowed_dirs() == [tmp_path.resolve()]


def test_getters_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_MAX_BYTES", "123")
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_TIMEOUT_SECONDS", "12.5")
    assert get_upload_max_bytes() == 123
    assert get_upload_timeout_seconds() == 12.5


def test_getters_invalid_env_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_MAX_BYTES", "not-an-int")
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_TIMEOUT_SECONDS", "not-a-float")
    assert get_upload_max_bytes() == _GB
    assert get_upload_timeout_seconds() == 3600.0


def test_getters_nonpositive_env_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_MAX_BYTES", "0")
    monkeypatch.setenv("AUTOMOX_MCP_UPLOAD_TIMEOUT_SECONDS", "-5")
    assert get_upload_max_bytes() == _GB
    assert get_upload_timeout_seconds() == 3600.0

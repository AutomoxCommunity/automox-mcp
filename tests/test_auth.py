"""Tests for MCP endpoint API key authentication."""

from __future__ import annotations

import textwrap

import pytest

from automox_mcp.auth import (
    _load_keys_from_env,
    _load_keys_from_file,
    _parse_key_entry,
    create_auth_provider,
    generate_api_key,
    is_auth_configured,
    load_api_keys,
)

# ---------------------------------------------------------------------------
# _parse_key_entry
# ---------------------------------------------------------------------------


class TestParseKeyEntry:
    def test_bare_key(self):
        result = _parse_key_entry("amx_mcp_abc123")
        assert result is not None
        token, meta = result
        assert token == "amx_mcp_abc123"
        assert meta["client_id"].startswith("client-")
        assert len(meta["client_id"]) == len("client-") + 8  # 8 hex chars
        assert meta["scopes"] == []

    def test_labelled_key(self):
        result = _parse_key_entry("my-client:amx_mcp_abc123")
        assert result is not None
        token, meta = result
        assert token == "amx_mcp_abc123"
        assert meta["client_id"] == "my-client"

    def test_labelled_key_with_whitespace(self):
        result = _parse_key_entry("  my-client : amx_mcp_abc123  ")
        assert result is not None
        token, meta = result
        assert token == "amx_mcp_abc123"
        assert meta["client_id"] == "my-client"

    def test_blank_line(self):
        assert _parse_key_entry("") is None
        assert _parse_key_entry("   ") is None

    def test_comment_line(self):
        assert _parse_key_entry("# this is a comment") is None

    def test_empty_token_after_colon(self):
        assert _parse_key_entry("my-client:") is None
        assert _parse_key_entry("my-client:   ") is None

    def test_stable_client_id(self):
        """Same bare key always produces the same client_id."""
        r1 = _parse_key_entry("token-abc")
        r2 = _parse_key_entry("token-abc")
        assert r1 is not None and r2 is not None
        assert r1[1]["client_id"] == r2[1]["client_id"]

    def test_different_keys_different_client_ids(self):
        r1 = _parse_key_entry("token-abc")
        r2 = _parse_key_entry("token-xyz")
        assert r1 is not None and r2 is not None
        assert r1[1]["client_id"] != r2[1]["client_id"]


# ---------------------------------------------------------------------------
# _load_keys_from_env
# ---------------------------------------------------------------------------


class TestLoadKeysFromEnv:
    def test_empty_env(self, monkeypatch):
        monkeypatch.delenv("AUTOMOX_MCP_API_KEYS", raising=False)
        assert _load_keys_from_env() == {}

    def test_single_key(self, monkeypatch):
        monkeypatch.setenv("AUTOMOX_MCP_API_KEYS", "amx_mcp_key1")
        tokens = _load_keys_from_env()
        assert "amx_mcp_key1" in tokens

    def test_multiple_keys(self, monkeypatch):
        monkeypatch.setenv("AUTOMOX_MCP_API_KEYS", "key1,key2,key3")
        tokens = _load_keys_from_env()
        assert len(tokens) == 3
        assert "key1" in tokens
        assert "key2" in tokens
        assert "key3" in tokens

    def test_labelled_keys_in_env(self, monkeypatch):
        monkeypatch.setenv("AUTOMOX_MCP_API_KEYS", "alice:key1,bob:key2")
        tokens = _load_keys_from_env()
        assert tokens["key1"]["client_id"] == "alice"
        assert tokens["key2"]["client_id"] == "bob"

    def test_whitespace_only(self, monkeypatch):
        monkeypatch.setenv("AUTOMOX_MCP_API_KEYS", "   ")
        assert _load_keys_from_env() == {}

    def test_trailing_comma(self, monkeypatch):
        monkeypatch.setenv("AUTOMOX_MCP_API_KEYS", "key1,")
        tokens = _load_keys_from_env()
        assert len(tokens) == 1
        assert "key1" in tokens


# ---------------------------------------------------------------------------
# _load_keys_from_file
# ---------------------------------------------------------------------------


class TestLoadKeysFromFile:
    def test_no_env_var(self, monkeypatch):
        monkeypatch.delenv("AUTOMOX_MCP_API_KEY_FILE", raising=False)
        assert _load_keys_from_file() == {}

    def test_nonexistent_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AUTOMOX_MCP_API_KEY_FILE", str(tmp_path / "nope.txt"))
        with pytest.raises(RuntimeError, match="non-existent file"):
            _load_keys_from_file()

    def test_file_with_keys(self, monkeypatch, tmp_path):
        key_file = tmp_path / "keys.txt"
        key_file.write_text(
            textwrap.dedent("""\
                # MCP endpoint API keys
                alice:amx_mcp_key1
                amx_mcp_key2

                # blank lines and comments are ignored
                bob:amx_mcp_key3
            """)
        )
        key_file.chmod(0o600)
        monkeypatch.setenv("AUTOMOX_MCP_API_KEY_FILE", str(key_file))

        tokens = _load_keys_from_file()
        assert len(tokens) == 3
        assert tokens["amx_mcp_key1"]["client_id"] == "alice"
        assert tokens["amx_mcp_key3"]["client_id"] == "bob"
        assert "amx_mcp_key2" in tokens

    def test_world_readable_file_rejected(self, monkeypatch, tmp_path):
        """V-127: world-readable key files must be refused."""
        key_file = tmp_path / "keys.txt"
        key_file.write_text("amx_mcp_key1\n")
        key_file.chmod(0o644)
        monkeypatch.setenv("AUTOMOX_MCP_API_KEY_FILE", str(key_file))
        with pytest.raises(RuntimeError, match="world-readable"):
            _load_keys_from_file()

    def test_empty_file(self, monkeypatch, tmp_path):
        key_file = tmp_path / "empty.txt"
        key_file.write_text("")
        key_file.chmod(0o600)
        monkeypatch.setenv("AUTOMOX_MCP_API_KEY_FILE", str(key_file))
        assert _load_keys_from_file() == {}


# ---------------------------------------------------------------------------
# load_api_keys (merging)
# ---------------------------------------------------------------------------


class TestLoadApiKeys:
    def test_env_overrides_file(self, monkeypatch, tmp_path):
        """Env var keys take precedence over file keys on collision."""
        key_file = tmp_path / "keys.txt"
        key_file.write_text("file-client:shared_token\n")
        key_file.chmod(0o600)
        monkeypatch.setenv("AUTOMOX_MCP_API_KEY_FILE", str(key_file))
        monkeypatch.setenv("AUTOMOX_MCP_API_KEYS", "env-client:shared_token")

        tokens = load_api_keys()
        assert tokens["shared_token"]["client_id"] == "env-client"

    def test_combines_sources(self, monkeypatch, tmp_path):
        key_file = tmp_path / "keys.txt"
        key_file.write_text("file_key\n")
        key_file.chmod(0o600)
        monkeypatch.setenv("AUTOMOX_MCP_API_KEY_FILE", str(key_file))
        monkeypatch.setenv("AUTOMOX_MCP_API_KEYS", "env_key")

        tokens = load_api_keys()
        assert "file_key" in tokens
        assert "env_key" in tokens

    def test_no_sources(self, monkeypatch):
        monkeypatch.delenv("AUTOMOX_MCP_API_KEYS", raising=False)
        monkeypatch.delenv("AUTOMOX_MCP_API_KEY_FILE", raising=False)
        assert load_api_keys() == {}


# ---------------------------------------------------------------------------
# create_auth_provider
# ---------------------------------------------------------------------------


class TestCreateAuthProvider:
    def test_returns_none_when_no_keys(self, monkeypatch):
        monkeypatch.delenv("AUTOMOX_MCP_API_KEYS", raising=False)
        monkeypatch.delenv("AUTOMOX_MCP_API_KEY_FILE", raising=False)
        assert create_auth_provider() is None

    def test_returns_provider_when_keys_set(self, monkeypatch):
        monkeypatch.setenv("AUTOMOX_MCP_API_KEYS", "test-key")
        provider = create_auth_provider()
        assert provider is not None

    @pytest.mark.asyncio
    async def test_provider_validates_correct_token(self, monkeypatch):
        monkeypatch.setenv("AUTOMOX_MCP_API_KEYS", "my-client:valid-token")
        provider = create_auth_provider()
        result = await provider.verify_token("valid-token")
        assert result is not None
        assert result.client_id == "my-client"

    @pytest.mark.asyncio
    async def test_provider_rejects_invalid_token(self, monkeypatch):
        monkeypatch.setenv("AUTOMOX_MCP_API_KEYS", "valid-token")
        provider = create_auth_provider()
        result = await provider.verify_token("wrong-token")
        assert result is None


# ---------------------------------------------------------------------------
# is_auth_configured
# ---------------------------------------------------------------------------


class TestIsAuthConfigured:
    def test_false_when_no_keys(self, monkeypatch):
        monkeypatch.delenv("AUTOMOX_MCP_API_KEYS", raising=False)
        monkeypatch.delenv("AUTOMOX_MCP_API_KEY_FILE", raising=False)
        assert is_auth_configured() is False

    def test_true_when_env_keys_set(self, monkeypatch):
        monkeypatch.setenv("AUTOMOX_MCP_API_KEYS", "test-key")
        assert is_auth_configured() is True


# ---------------------------------------------------------------------------
# generate_api_key
# ---------------------------------------------------------------------------


class TestGenerateApiKey:
    def test_default_prefix(self):
        key = generate_api_key()
        assert key.startswith("amx_mcp_")
        # 32 hex chars after prefix
        assert len(key) == len("amx_mcp_") + 32

    def test_custom_prefix(self):
        key = generate_api_key(prefix="test")
        assert key.startswith("test_mcp_")

    def test_uniqueness(self):
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100  # all unique

    def test_hex_chars_only(self):
        key = generate_api_key()
        hex_part = key.split("_mcp_")[1]
        int(hex_part, 16)  # raises if not valid hex


# ---------------------------------------------------------------------------
# CLI --generate-key
# ---------------------------------------------------------------------------


class TestGenerateKeyCLI:
    def test_generate_key_prints_and_exits(self, capsys, monkeypatch):
        """--generate-key should print a key and return without starting server."""
        # Prevent env validation from failing
        monkeypatch.setenv("AUTOMOX_API_KEY", "fake")
        monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "fake")
        monkeypatch.setenv("AUTOMOX_ORG_ID", "1")

        from automox_mcp import main

        main(["--generate-key"])
        captured = capsys.readouterr()
        assert captured.out.strip().startswith("amx_mcp_")

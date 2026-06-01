"""Local-file upload guard for ``upload_policy_file`` (see docs/api-coverage.md).

The installer upload reads a file from the **local filesystem** and streams it
to Automox. To keep that arbitrary-file-read surface contained, every path is:

  - canonicalized (``..`` and symlinks fully resolved) *before* any check,
  - required to live inside one of the ``AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS``
    directories,
  - required to be an existing regular file within the size cap.

Combined with stdio-only registration and ``main()`` refusing to start a remote
transport while the upload flag is on, this confines reads to operator-approved
directories on the operator's own machine.
"""

from __future__ import annotations

import os
from pathlib import Path

# Automox's Required Software ceiling is 10 GB (product docs). Default the cap to
# that so valid installers are never rejected; operators may lower it.
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024 * 1024  # 10 GiB
_DEFAULT_TIMEOUT_SECONDS = 3600.0


def get_upload_allowed_dirs() -> list[Path]:
    """Resolved absolute directories the upload tool may read from.

    From ``AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS`` (comma-separated). Entries that do
    not resolve to an existing directory are dropped — fail-closed: a typo'd
    entry silently narrows the allowlist rather than widening it.
    """
    raw = os.environ.get("AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS", "")
    dirs: list[Path] = []
    for part in raw.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        try:
            resolved = Path(candidate).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if resolved.is_dir():
            dirs.append(resolved)
    return dirs


def get_upload_max_bytes() -> int:
    """Max upload size in bytes (``AUTOMOX_MCP_UPLOAD_MAX_BYTES``, default 10 GiB)."""
    raw = os.environ.get("AUTOMOX_MCP_UPLOAD_MAX_BYTES", "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return _DEFAULT_MAX_BYTES
        if value > 0:
            return value
    return _DEFAULT_MAX_BYTES


def get_upload_timeout_seconds() -> float:
    """Upload read/write timeout (``AUTOMOX_MCP_UPLOAD_TIMEOUT_SECONDS``, default 3600)."""
    raw = os.environ.get("AUTOMOX_MCP_UPLOAD_TIMEOUT_SECONDS", "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return _DEFAULT_TIMEOUT_SECONDS
        if value > 0:
            return value
    return _DEFAULT_TIMEOUT_SECONDS


def validate_upload_path(file_path: str) -> Path:
    """Resolve and authorize *file_path* for upload, returning the resolved path.

    Raises ``ValueError`` (surfaced to the model as a validation error) when the
    allowlist is unset, or the path is missing, not a regular file, outside the
    allowlist, empty, or too large. Returns the **resolved** path so the caller
    opens the canonical target (not the original, possibly-symlinked input).
    """
    allowed = get_upload_allowed_dirs()
    if not allowed:
        raise ValueError(
            "upload_policy_file is not configured: set AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS "
            "to one or more absolute directories the server may read installers from."
        )

    try:
        resolved = Path(file_path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("file_path does not exist or could not be resolved.") from exc

    if not resolved.is_file():
        raise ValueError("file_path must point to a regular file.")

    # Containment check on fully-resolved endpoints — defeats `..` traversal and
    # symlink escape, since both the file and each base are canonicalized first.
    if not any(resolved.is_relative_to(base) for base in allowed):
        raise ValueError(
            "file_path is outside the allowed upload directories (AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS)."
        )

    size = resolved.stat().st_size
    if size == 0:
        raise ValueError("file_path is an empty file.")
    max_bytes = get_upload_max_bytes()
    if size > max_bytes:
        raise ValueError(
            f"file is {size} bytes, exceeding the {max_bytes}-byte upload limit "
            "(AUTOMOX_MCP_UPLOAD_MAX_BYTES)."
        )
    return resolved

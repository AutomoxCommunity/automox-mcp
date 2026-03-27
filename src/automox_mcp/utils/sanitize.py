"""Sanitize untrusted API data before it reaches the LLM.

Mitigates indirect prompt injection by stripping markdown exfiltration
vectors, fenced code blocks with shell commands, and instruction-like
prefixes from user-controllable text fields.

Controlled by ``AUTOMOX_MCP_SANITIZE_RESPONSES`` (default: ``true``).
Set to ``false`` to disable when sanitization is handled at the gateway.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def is_sanitization_enabled() -> bool:
    """Return True unless explicitly disabled via env var."""
    value = os.environ.get("AUTOMOX_MCP_SANITIZE_RESPONSES", "true")
    return value.strip().lower() not in {"0", "false", "no", "off"}


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Markdown image: ![alt](url) → alt
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")

# Markdown link: [text](url) → text
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]+\)")

# Fenced code blocks with shell/script content
_CODE_BLOCK_RE = re.compile(
    r"```(?:bash|sh|shell|zsh|python|py|powershell|pwsh|cmd|bat)[^\S\n]*\n.*?```",
    re.DOTALL | re.IGNORECASE,
)

# Unlabeled fenced code blocks (any content between triple backticks)
_UNLABELED_CODE_BLOCK_RE = re.compile(r"```[^\S\n]*\n.*?```", re.DOTALL)

# Triple backticks (that aren't part of a code block we already removed)
_TRIPLE_BACKTICK_RE = re.compile(r"```")

# Zero-width and invisible Unicode characters used for homoglyph bypass
_INVISIBLE_CHARS_RE = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad\u2060\u2061\u2062\u2063\u2064\u180e]"
)

# Markdown reference-style images/links: ![alt][ref] or [text][ref]
_REF_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\[[^\]]+\]")
_REF_LINK_RE = re.compile(r"\[([^\]]*)\]\[[^\]]+\]")
# Reference definitions: [ref]: url
_REF_DEF_RE = re.compile(r"^\[[^\]]+\]:\s+\S+", re.MULTILINE)

# Instruction prefixes — matched only at line start, case-insensitive.
# This is a best-effort defense; supplement with gateway-level guardrails
# for sensitive deployments.
_INSTRUCTION_PREFIX_RE = re.compile(
    r"^(?:"
    r"IMPORTANT|SYSTEM|INSTRUCTION|IGNORE|OVERRIDE|ATTENTION|CRITICAL|"
    r"DISREGARD|FORGET|NOTE|PRIORITY|URGENT|ALERT|REMINDER|WARNING|"
    r"CAUTION|ACTION REQUIRED|"
    r"You are|Act as|You must|Do not|Ignore (?:all |previous )|"
    r"Forget (?:all |your )|From now on|New instructions|"
    r"<\/?system>|<\/?instruction>"
    r")[:\s]",
    re.IGNORECASE | re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Field classification
# ---------------------------------------------------------------------------

# Fields where instruction-prefix stripping is safe to apply.
# These are free-text fields where users write descriptions/notes.
_INSTRUCTION_STRIP_FIELDS: frozenset[str] = frozenset(
    {
        "notes",
        "description",
        "details",
        "data",
        "message",
        "result_reason",
        "stdout",
        "stderr",
    }
)

# Fields where instruction-prefix stripping should NOT apply because
# users commonly use words like "IMPORTANT" or "SYSTEM" in names/tags.
# Universal sanitization (links, images, code blocks) still applies.
_PRESERVE_PREFIX_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "display_name",
        "custom_name",
        "hostname",
        "tags",
        "policy_name",
        "server_name",
        "activity",
        "title",
    }
)

# ---------------------------------------------------------------------------
# Core sanitization functions
# ---------------------------------------------------------------------------


def sanitize_for_llm(text: str, *, field_name: str | None = None) -> str:
    """Sanitize a single string value.

    Steps applied universally (all string fields):
      1. Strip markdown image syntax
      2. Strip markdown link syntax
      3. Remove fenced code blocks with shell/script commands
      4. Escape remaining triple backticks

    Step applied only to free-text fields (not names/tags):
      5. Remove lines starting with instruction prefixes
    """
    if not text:
        return text

    original = text

    # Step 0: Normalize Unicode to NFKC and strip invisible characters.
    # Defeats homoglyph attacks (Cyrillic/full-width lookalikes) and
    # zero-width character insertion used to evade prefix detection.
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE_CHARS_RE.sub("", text)

    # Step 1-2: Markdown images and links (inline and reference-style)
    text = _IMAGE_RE.sub(r"\1", text)
    text = _REF_IMAGE_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _REF_LINK_RE.sub(r"\1", text)
    text = _REF_DEF_RE.sub("", text)

    # Step 3: Fenced code blocks (labelled shell/script, then unlabeled)
    text = _CODE_BLOCK_RE.sub("", text)
    text = _UNLABELED_CODE_BLOCK_RE.sub("", text)

    # Step 4: Escape remaining triple backticks
    text = _TRIPLE_BACKTICK_RE.sub("`", text)

    # Step 5: Instruction prefix removal (free-text fields only)
    apply_prefix_strip = field_name is not None and field_name.lower() in _INSTRUCTION_STRIP_FIELDS
    if apply_prefix_strip:
        text = _INSTRUCTION_PREFIX_RE.sub("", text)

    if text != original:
        logger.debug(
            "Sanitized field=%s preview=%r",
            field_name or "(unknown)",
            original[:80],
        )

    return text.strip() if text != original else text


_MAX_SANITIZE_DEPTH = 10


def sanitize_dict(data: Any, *, _depth: int = 0) -> Any:
    """Recursively sanitize all string values in a dict/list structure.

    Applies field-aware sanitization: names/tags get universal sanitization
    only, while notes/descriptions also get instruction-prefix stripping.

    Skips non-string values (numbers, booleans, None).
    """
    if _depth > _MAX_SANITIZE_DEPTH:
        logger.debug(
            "Sanitization depth limit (%d) reached; redacting nested data",
            _MAX_SANITIZE_DEPTH,
        )
        if isinstance(data, str):
            return sanitize_for_llm(data)
        return "[redacted: max depth exceeded]"

    if isinstance(data, Mapping):
        result: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str) and value:
                result[key] = sanitize_for_llm(value, field_name=str(key))
            elif isinstance(value, (Mapping, list)):
                result[key] = sanitize_dict(value, _depth=_depth + 1)
            else:
                result[key] = value
        return result

    if isinstance(data, list):
        return [sanitize_dict(item, _depth=_depth + 1) for item in data]

    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "is_sanitization_enabled",
    "sanitize_dict",
    "sanitize_for_llm",
]

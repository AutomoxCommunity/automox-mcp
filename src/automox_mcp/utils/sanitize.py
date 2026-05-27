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
from html.parser import HTMLParser
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

# Markdown image: ![alt](url) → alt  (supports one level of nested brackets)
_IMAGE_RE = re.compile(r"!\[((?:[^\[\]]|\[[^\]]*\])*)\]\([^)]+\)")

# Markdown link: [text](url) → text  (supports one level of nested brackets)
_LINK_RE = re.compile(r"\[((?:[^\[\]]|\[[^\]]*\])*)\]\([^)]+\)")

# Fenced code blocks with shell/script content (supports 3+ backtick delimiters)
_CODE_BLOCK_RE = re.compile(
    r"`{3,}(?:bash|sh|shell|zsh|python|py|powershell|pwsh|cmd|bat)[^\S\n]*\n.*?`{3,}",
    re.DOTALL | re.IGNORECASE,
)

# Fenced code blocks with any or no language label (catch-all for labels not
# matched by _CODE_BLOCK_RE, e.g. ```javascript, ```ruby, or unlabeled ```)
_UNLABELED_CODE_BLOCK_RE = re.compile(r"`{3,}[^\n]*\n.*?`{3,}", re.DOTALL)

# Triple-or-more backticks (that aren't part of a code block we already removed)
_TRIPLE_BACKTICK_RE = re.compile(r"`{3,}")

# ---------------------------------------------------------------------------
# HTML stripping via stdlib parser (replaces regex-based tag filtering)
# ---------------------------------------------------------------------------

_DANGEROUS_TAGS = frozenset({"script", "style"})
_DANGEROUS_PROTOCOL_RE = re.compile(r"^\s*(?:javascript|data):", re.IGNORECASE)
_EVENT_HANDLER_RE = re.compile(r"^on\w+$", re.IGNORECASE)


class _HTMLTextExtractor(HTMLParser):
    """Extract safe text from HTML, dropping tags and dangerous content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._pieces: list[str] = []
        self._skip_depth: int = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _DANGEROUS_TAGS:
            self._skip_depth += 1
            return
        for attr_name, attr_value in attrs:
            if _EVENT_HANDLER_RE.match(attr_name):
                return
            if (
                attr_value
                and attr_name.lower() in ("href", "src", "action")
                and _DANGEROUS_PROTOCOL_RE.match(attr_value)
            ):
                return

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _DANGEROUS_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._pieces.append(data)

    def get_text(self) -> str:
        return "".join(self._pieces)


def _strip_html(text: str) -> str:
    """Strip HTML tags and dangerous content using a proper parser."""
    if "<" not in text:
        return text
    parser = _HTMLTextExtractor()
    parser.feed(text)
    return parser.get_text()


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
        "comments",
        "reason",
        "summary",
        "output",
        "body",
        "content",
        "text",
        "value",
        "result",
        "response",
        "log",
        "error",
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

    # Step 3-4: Strip HTML tags and dangerous content (script, event handlers,
    # JS/data URIs) using a proper parser instead of regex.
    text = _strip_html(text)

    # Step 5: Fenced code blocks (labelled shell/script, then unlabeled)
    text = _CODE_BLOCK_RE.sub("", text)
    text = _UNLABELED_CODE_BLOCK_RE.sub("", text)

    # Step 6: Escape remaining triple backticks
    text = _TRIPLE_BACKTICK_RE.sub("`", text)

    # Step 7: Instruction prefix removal (free-text fields only, or unknown fields)
    # Apply to known free-text fields and any field not in the preserve-list
    apply_prefix_strip = field_name is None or (field_name.lower() not in _PRESERVE_PREFIX_FIELDS)
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
        result_list: list[Any] = []
        for item in data:
            if isinstance(item, str) and item:
                result_list.append(sanitize_for_llm(item))
            elif isinstance(item, (Mapping, list)):
                result_list.append(sanitize_dict(item, _depth=_depth + 1))
            else:
                result_list.append(item)
        return result_list

    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "is_sanitization_enabled",
    "sanitize_dict",
    "sanitize_for_llm",
]

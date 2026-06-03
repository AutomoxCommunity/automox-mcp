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

# Fast-path triggers: any string containing one of these chars MIGHT match a
# downstream regex, so we run the full pipeline. ASCII strings containing none
# of these characters cannot match any of our markdown/HTML/code-block regexes
# and skip straight to the instruction-prefix check.
# The set deliberately includes bidirectional/zero-width control characters:
# they are *scan targets* (TrojanSource-style payloads we detect), not source
# obfuscation — hence the nosec on the literal below.
_SANITIZE_TRIGGER_CHARS: frozenset[str] = frozenset(
    "[!`<​‌‍‎‏﻿­⁠⁡⁢⁣⁤᠎"  # nosec B613
)

# Cheap prefix probe — matches the start of *any line* that might contain an
# instruction prefix. Multi-line aware so the fast-path doesn't miss a prefix
# on line 2+ of a notes/description field. The keyword regex is the full
# alternation; this probe just checks the first letter so we skip strings
# that can't possibly match (the vast majority of API values: UUIDs,
# statuses, numeric strings).
_INSTRUCTION_PREFIX_PROBE = re.compile(
    r"^\s*(?:I|S|O|A|C|D|F|N|P|U|R|W|Y|<)", re.IGNORECASE | re.MULTILINE
)


class _HTMLTextExtractor(HTMLParser):
    """Extract safe text from HTML, dropping tags and dangerous content.

    Text inside a dangerous *element* is suppressed. An element is dangerous if
    its tag is in ``_DANGEROUS_TAGS`` (``script``/``style``) **or** it carries a
    dangerous attribute (an ``on*`` event handler, or a ``javascript:``/``data:``
    URL in ``href``/``src``/``action``). In every case the tag and its attributes
    are dropped; only text nodes survive, so the dangerous attribute value itself
    never reaches the output — suppressing the element's text is defence in depth.

    Suppression is tracked with a stack of ``(tag, skipping)`` frames rather than a
    bare depth counter so that:

    * a dangerous attribute on an arbitrary tag (e.g. ``<a onclick=...>``) is
      released by its matching end tag — a counter keyed on ``_DANGEROUS_TAGS``
      alone would never decrement and would silently swallow all trailing text;
    * **void** elements (``<img>``, ``<br>``, ...) emit a start tag with no end
      tag, so they are never pushed (they have no text content to suppress and a
      pushed frame would leak);
    * unclosed inner tags are tolerated — an end tag pops down to its matching
      frame.

    ``<script>``/``<style>`` are parsed by ``HTMLParser`` in CDATA mode, so their
    raw body (including any ``</a>``-looking text) arrives as a single data event
    and cannot desynchronise the stack.
    """

    # Elements with no end tag in the HTML spec — never pushed onto the stack.
    _VOID_ELEMENTS = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._pieces: list[str] = []
        # Stack of (tag_name, skipping) for currently-open non-void elements.
        self._stack: list[tuple[str, bool]] = []

    def _skipping(self) -> bool:
        return bool(self._stack and self._stack[-1][1])

    def _is_dangerous(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag.lower() in _DANGEROUS_TAGS:
            return True
        for attr_name, attr_value in attrs:
            if _EVENT_HANDLER_RE.match(attr_name):
                return True
            if (
                attr_value
                and attr_name.lower() in ("href", "src", "action")
                and _DANGEROUS_PROTOCOL_RE.match(attr_value)
            ):
                return True
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        skipping = self._skipping() or self._is_dangerous(tag, attrs)
        if tag.lower() not in self._VOID_ELEMENTS:
            self._stack.append((tag.lower(), skipping))

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == t:
                del self._stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if not self._skipping():
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

    # Fast-path: short ASCII strings with no markdown/HTML/zero-width triggers
    # can only ever match the instruction-prefix regex. A cheap leading-char
    # probe filters out almost every API value (UUIDs, statuses, timestamps,
    # numeric strings) before any of the ~8 substitution passes below. Saves a
    # significant fraction of total request time on large list responses where
    # most strings are short identifiers.
    if text.isascii() and not any(c in text for c in _SANITIZE_TRIGGER_CHARS):
        apply_prefix_strip = field_name is None or (
            field_name.lower() not in _PRESERVE_PREFIX_FIELDS
        )
        if not apply_prefix_strip or not _INSTRUCTION_PREFIX_PROBE.search(text):
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

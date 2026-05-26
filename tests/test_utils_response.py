"""Tests for canonical pagination metadata helper (issue #52)."""

from __future__ import annotations

from automox_mcp.utils.response import build_pagination_metadata

# ---------------------------------------------------------------------------
# build_pagination_metadata — canonical shape unit tests
# ---------------------------------------------------------------------------


def test_emits_canonical_fields_when_supplied() -> None:
    block = build_pagination_metadata(
        page=2,
        page_size=10,
        total_elements=53,
        has_more=True,
    )
    assert block == {
        "page": 2,
        "page_size": 10,
        "total_elements": 53,
        "total_pages": 6,  # ceil(53 / 10)
        "has_more": True,
    }


def test_derives_total_pages_from_total_elements_and_page_size() -> None:
    assert build_pagination_metadata(page_size=20, total_elements=100)["total_pages"] == 5
    assert build_pagination_metadata(page_size=20, total_elements=101)["total_pages"] == 6
    assert build_pagination_metadata(page_size=20, total_elements=0)["total_pages"] == 0


def test_derives_has_more_when_all_inputs_present() -> None:
    # Page 0 of 5 pages → more available.
    block = build_pagination_metadata(page=0, page_size=10, total_elements=42)
    assert block["has_more"] is True
    # Last page → no more.
    block = build_pagination_metadata(page=4, page_size=10, total_elements=42)
    assert block["has_more"] is False


def test_does_not_derive_has_more_when_inputs_missing() -> None:
    assert "has_more" not in build_pagination_metadata(page=0, page_size=10)
    assert "has_more" not in build_pagination_metadata(total_elements=100)


def test_explicit_has_more_overrides_derivation() -> None:
    block = build_pagination_metadata(page=0, page_size=10, total_elements=42, has_more=False)
    assert block["has_more"] is False


def test_cursor_based_emits_next_cursor_and_has_more() -> None:
    block = build_pagination_metadata(
        page_size=25, has_more=True, next_cursor="opaque-cursor-string"
    )
    assert block == {
        "page_size": 25,
        "has_more": True,
        "next_cursor": "opaque-cursor-string",
    }


def test_omits_none_fields() -> None:
    assert build_pagination_metadata() == {}
    assert build_pagination_metadata(page=0) == {"page": 0}


def test_extra_fields_merged_only_when_not_overriding_canonical() -> None:
    block = build_pagination_metadata(
        page=1,
        page_size=10,
        total_elements=30,
        extra={"limit": 10, "total_count": 30, "page": 999},
    )
    # Canonical `page` from the kwarg wins; legacy `limit`/`total_count` are
    # merged in for backwards-compat with pre-#52 callers.
    assert block["page"] == 1
    assert block["limit"] == 10
    assert block["total_count"] == 30


def test_extra_skips_none_values() -> None:
    block = build_pagination_metadata(page=0, extra={"sort": None, "first": True})
    assert "sort" not in block
    assert block["first"] is True

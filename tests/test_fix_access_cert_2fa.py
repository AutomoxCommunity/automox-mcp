"""Regression test for the 2FA-status inversion in the access-certification App.

Bug #10 (WRONG_DATA · High): the generated review UI classified the ``tfa_type``
field with bare JavaScript truthiness. The Automox field carries the LITERAL
STRING ``'disabled'`` (not null) when 2FA is OFF, so a disabled account rendered
green ("2FA: disabled") — the exact inverse of reality. The fix replaces the
raw-truthiness logic with a ``tfaState`` classifier: ``'disabled'``/``'disable'``/
``'none'``/``''`` (case-insensitive, trimmed) → OFF, null/absent → UNKNOWN, any
other non-empty value → genuinely ENABLED.

The UI is a generated string, so the practical input->output assertion is that
the rendered template contains the corrected classifier and no longer keys the
on/off class off bare truthiness.
"""

from __future__ import annotations

from automox_mcp.resources.access_certification_app import (
    _ACCESS_CERTIFICATION_HTML,
)


def test_classifier_present_and_handles_disabled_string() -> None:
    """A tfaState helper exists and treats the literal 'disabled' string as OFF."""
    html = _ACCESS_CERTIFICATION_HTML
    assert "function tfaState(" in html
    # The literal 'disabled' (and siblings) must be classified as OFF, not green.
    assert '"disabled"' in html
    assert '"none"' in html


def test_no_bare_truthiness_for_tfa_class() -> None:
    """The on/off class is no longer derived from bare truthiness of tfa_type."""
    html = _ACCESS_CERTIFICATION_HTML
    # The old inverted logic keyed the class off (tfa ? "on" : "off").
    assert '(tfa ? "on" : "off")' not in html
    assert '(tfa ? "2FA: " + esc(tfa) : "⚠ no 2FA")' not in html


def test_explicit_unknown_state_for_null() -> None:
    """null/absent tfa_type renders a neutral unknown state, not green."""
    html = _ACCESS_CERTIFICATION_HTML
    assert "tfa.unknown" in html
    assert '"unknown"' in html


def test_class_and_label_driven_by_classifier() -> None:
    """The rendered row keys both the CSS class and label off the classifier."""
    html = _ACCESS_CERTIFICATION_HTML
    assert "var tfaCls = tfaState(tfa);" in html
    assert "class=\"tfa ' + tfaCls + '\"" in html

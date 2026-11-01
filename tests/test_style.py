"""Tests for CLI terminal styling and colour helpers."""

import sys
import pytest

from decisionlens.style import colour_enabled, format_warning_cli, paint, status_colour


def test_paint_returns_plain_text_when_not_a_tty(monkeypatch):
    """Verify paint() returns unchanged text when stdout is not a TTY."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    assert colour_enabled() is False
    assert paint("sample text", "red") == "sample text"
    assert paint("sample text", "green", bold=True) == "sample text"
    assert paint("sample text", "cyan", bold=True) == "sample text"


def test_paint_returns_plain_text_when_no_color_set(monkeypatch):
    """Verify paint() returns unchanged text when NO_COLOR environment variable is set."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    assert colour_enabled() is False
    assert paint("sample text", "red") == "sample text"
    assert paint("sample text", "yellow", bold=True) == "sample text"


def test_paint_wraps_in_ansi_codes_when_enabled(monkeypatch):
    """Verify paint() wraps in ANSI escape codes when colour is enabled."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    assert colour_enabled() is True
    red_text = paint("alert", "red")
    assert red_text == "\033[31malert\033[0m"

    bold_cyan = paint("TITLE:", "cyan", bold=True)
    assert bold_cyan == "\033[1;36mTITLE:\033[0m"


def test_status_colour():
    """Verify status_colour returns expected colour per status according to specification."""
    assert status_colour("REJECTED") == "red"
    assert status_colour("rejected") == "red"
    assert status_colour("ACCEPTED") == "green"
    assert status_colour("accepted") == "green"
    assert status_colour("UNRESOLVED") == "yellow"
    assert status_colour("unresolved") == "yellow"
    assert status_colour("LOW_CONFIDENCE") == "magenta"
    assert status_colour("low_confidence") == "magenta"
    assert status_colour("UNKNOWN") == "white"
    assert status_colour("") == "white"


def test_format_warning_cli_plain_when_disabled(monkeypatch):
    """Verify format_warning_cli formats warning with capitals and no ANSI codes when colour is disabled."""
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    warning_item = {
        "match_type": "strong",
        "warning": (
            "PR touches parser/core.c which is tied to past decision 'Retain C'. "
            "Rejected idea: Rewrite in Rust. Reason: Slower. Status: REJECTED. "
            "Previously decided: Stays C. (warning text written by: template)"
        ),
        "sources": ["https://example.com/1", "https://example.com/2"],
    }

    formatted = format_warning_cli(warning_item)
    assert "\033[" not in formatted
    assert "[STRONG] PR touches parser/core.c (decision: Retain C)" in formatted
    assert "  REJECTED IDEA: Rewrite in Rust" in formatted
    assert "  REASON: Slower." in formatted
    assert "  STATUS: REJECTED" in formatted
    assert "  PREVIOUSLY DECIDED: Stays C." in formatted
    assert "  SOURCES:\n    - https://example.com/1\n    - https://example.com/2" in formatted
    assert "(warning text written by: template)" in formatted


def test_format_warning_cli_with_colour(monkeypatch):
    """Verify format_warning_cli applies ANSI codes when colour is enabled."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    warning_item = {
        "match_type": "strong",
        "warning": (
            "PR touches parser/core.c. Rejected idea: Rust. Reason: Perf. "
            "Status: REJECTED. Previously decided: C. (warning text written by: template)"
        ),
        "sources": ["https://example.com/1"],
    }

    formatted = format_warning_cli(warning_item)
    assert "\033[" in formatted
    assert "\033[31m[STRONG]\033[0m" in formatted
    assert "\033[1;36mREJECTED IDEA:\033[0m" in formatted
    assert "\033[1;36mREASON:\033[0m" in formatted
    assert "\033[1;36mSTATUS:\033[0m" in formatted
    assert "\033[31mREJECTED\033[0m" in formatted
    assert "\033[1;36mPREVIOUSLY DECIDED:\033[0m" in formatted
    assert "\033[1;36mSOURCES:\033[0m" in formatted
    assert "\033[34mhttps://example.com/1\033[0m" in formatted
    assert "\033[2;37m(warning text written by: template)\033[0m" in formatted

"""Tests for Markdown report generation in DecisionLens."""

from pathlib import Path
import pytest

from decisionlens.__main__ import main
from decisionlens.models import Claim, DecisionRecord
from decisionlens.pipeline import save_records
from decisionlens.report import write_report


def test_report_contains_quote_url_and_status(tmp_path):
    """Verify that the Markdown report contains the quote, URL, and status."""
    quote_text = "PR #145 was reverted and parser/core.c will remain implemented in C."
    source_url = "https://github.com/example-org/fastparser/issues/142#issuecomment-1008"

    record = DecisionRecord(
        id="DEC-001",
        title="Retain C parser",
        status="REJECTED",
        decided="parser/core.c will remain in C with AddressSanitizer and LibFuzzer in CI",
        rejected=[
            {
                "idea": "Rewrite parser/core.c in Rust",
                "why": "2x slower in benchmarks compared to C",
            }
        ],
        sources=[
            Claim(
                comment_id="c8",
                quote=quote_text,
                url=source_url,
            )
        ],
        linked_code=["parser/core.c"],
        uncertainties=["Verified claim in c8"],
    )

    report_file = tmp_path / "report.md"
    write_report([record], report_file)

    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")

    # Verify status
    assert "REJECTED" in content

    # Verify quote
    assert quote_text in content

    # Verify URL and comment id
    assert source_url in content
    assert "c8" in content

    # Verify rejected alternative and linked code
    assert "Rewrite parser/core.c in Rust" in content
    assert "2x slower in benchmarks" in content
    assert "parser/core.c" in content

    # Verify Unverified section
    assert "Unverified Notes" in content


def test_report_empty_records_gives_valid_report(tmp_path):
    """Verify that an empty records list produces a valid Markdown report without crashing."""
    report_file = tmp_path / "empty_report.md"
    write_report([], report_file)

    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")

    assert content.startswith("# DecisionLens Recovery Report")
    assert "No decision records found." in content


def test_cli_report_command(tmp_path):
    """Verify CLI report command generates Markdown report from decisions JSON."""
    decisions_file = tmp_path / "decisions.json"
    report_file = tmp_path / "cli_report.md"

    record = DecisionRecord(
        id="DEC-042",
        title="CLI Test Decision",
        status="ACCEPTED",
        decided="Use SQLite database",
        sources=[
            Claim(
                comment_id="c1",
                quote="We should adopt SQLite for local storage.",
                url="https://example.com/issue/1#c1",
            )
        ],
    )
    save_records([record], decisions_file)

    main(["report", str(decisions_file), "--out", str(report_file)])

    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "CLI Test Decision" in content
    assert "ACCEPTED" in content
    assert "We should adopt SQLite for local storage." in content
    assert "https://example.com/issue/1#c1" in content

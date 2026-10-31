"""Terminal styling and ANSI colour helpers for DecisionLens CLI."""

from __future__ import annotations

import os
import re
import sys
from typing import Any

ANSI_COLOURS: dict[str, str] = {
    "black": "30",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "white": "37",
    "grey": "90",
    "gray": "90",
    "dim_grey": "2;37",
    "dim_gray": "2;37",
}


def colour_enabled() -> bool:
    """Return True only if sys.stdout is a tty and NO_COLOR env var is not set."""
    if "NO_COLOR" in os.environ:
        return False
    if not hasattr(sys.stdout, "isatty"):
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def paint(text: str, colour: str, bold: bool = False) -> str:
    """Wrap text in ANSI escape codes if colour is enabled, otherwise return text unchanged."""
    if not colour_enabled() or not text:
        return text

    codes: list[str] = []
    if bold:
        codes.append("1")

    colour_key = (colour or "").lower().replace("-", "_")
    if colour_key in ("dim_grey", "dim_gray"):
        codes.append("2;37")
    elif colour_key == "dim":
        codes.append("2")
    elif colour_key in ANSI_COLOURS:
        codes.append(ANSI_COLOURS[colour_key])

    if not codes:
        return text

    code_str = ";".join(codes)
    return f"\033[{code_str}m{text}\033[0m"


def status_colour(status: str) -> str:
    """Return colour name according to status.

    REJECTED red, ACCEPTED green, UNRESOLVED yellow, LOW_CONFIDENCE magenta, anything else white.
    """
    st = (status or "").strip().upper()
    if st == "REJECTED":
        return "red"
    if st == "ACCEPTED":
        return "green"
    if st == "UNRESOLVED":
        return "yellow"
    if st == "LOW_CONFIDENCE":
        return "magenta"
    return "white"


def format_warning_cli(w: Any) -> str:
    """Format a warning item for CLI output with readable colours and multi-line layout."""
    match_type = str(w.get("match_type", "")).upper()
    if match_type == "STRONG":
        match_str = paint("[STRONG]", "red")
    elif match_type == "POSSIBLE":
        match_str = paint("[POSSIBLE]", "yellow")
    elif match_type:
        match_str = paint(f"[{match_type}]", "white")
    else:
        match_str = ""

    warning_text = str(w.get("warning", "")).strip()

    # Extract "(warning text written by: ...)"
    writer_match = re.search(r"\(warning text written by: [^)]+\)", warning_text)
    writer_str = writer_match.group(0) if writer_match else ""
    if writer_match:
        warning_text = (
            warning_text[:writer_match.start()] + warning_text[writer_match.end():]
        ).strip()

    # Extract "Previously decided: ..."
    decided_text = ""
    decided_match = re.search(
        r"\bPreviously decided:\s*(.*)$", warning_text, flags=re.IGNORECASE
    )
    if decided_match:
        decided_text = decided_match.group(1).strip()
        warning_text = warning_text[:decided_match.start()].strip()

    # Extract "Status: <status>"
    status_text = ""
    status_match = re.search(
        r"\bStatus:\s*([A-Za-z0-9_]+)\.?", warning_text, flags=re.IGNORECASE
    )
    if status_match:
        status_text = status_match.group(1).strip()
        warning_text = (
            warning_text[:status_match.start()] + warning_text[status_match.end():]
        ).strip()
    elif w.get("status"):
        status_text = str(w.get("status")).strip()

    # Extract all "Rejected idea: <idea>. Reason: <why>."
    rejected_pairs: list[tuple[str, str]] = []
    first_rej = re.search(r"\bRejected idea:\s*", warning_text, flags=re.IGNORECASE)
    if first_rej:
        rej_section = warning_text[first_rej.start():].strip()
        header_text = warning_text[:first_rej.start()].strip()

        items = re.split(r"\bRejected idea:\s*", rej_section, flags=re.IGNORECASE)
        for item in items:
            if not item.strip():
                continue
            parts = re.split(r"\bReason:\s*", item, maxsplit=1, flags=re.IGNORECASE)
            idea_val = parts[0].strip().rstrip(".")
            reason_val = parts[1].strip() if len(parts) > 1 else ""
            rejected_pairs.append((idea_val, reason_val))
    else:
        header_text = warning_text

    # Format header sentence: "PR touches <files> (decision: <title>)"
    m_touch = re.search(
        r"^(PR touches .*?)\s*which is tied to past decision\s*['\"]?(.*?)['\"]?\.?$",
        header_text,
        flags=re.IGNORECASE,
    )
    if m_touch:
        header_sentence = f"{m_touch.group(1)} (decision: {m_touch.group(2)})"
    else:
        m_possible = re.search(
            r"^(Possible conflict.*?)\s*with past decision\s*['\"]?(.*?)['\"]?\s+on topic\s+['\"]?(.*?)['\"]?\.?$",
            header_text,
            flags=re.IGNORECASE,
        )
        if m_possible:
            header_sentence = (
                f"{m_possible.group(1)} on topic '{m_possible.group(3)}' "
                f"(decision: {m_possible.group(2)})"
            )
        else:
            header_sentence = header_text.rstrip(".")
            if (
                w.get("title")
                and "(decision:" not in header_sentence
                and header_sentence.startswith("PR touches")
            ):
                header_sentence = f"{header_sentence} (decision: {w.get('title')})"

    out_lines: list[str] = []

    # 1. Match header line
    if match_str and header_sentence:
        out_lines.append(f"{match_str} {header_sentence}")
    elif match_str:
        out_lines.append(match_str)
    elif header_sentence:
        out_lines.append(header_sentence)

    # 2. REJECTED IDEA: and REASON: lines
    for idea, reason in rejected_pairs:
        out_lines.append(f"  {paint('REJECTED IDEA:', 'cyan', bold=True)} {idea}")
        if reason:
            out_lines.append(f"  {paint('REASON:', 'cyan', bold=True)} {reason}")

    # 3. STATUS: <STATUS>
    if status_text:
        st_styled = paint(status_text.upper(), status_colour(status_text))
        out_lines.append(f"  {paint('STATUS:', 'cyan', bold=True)} {st_styled}")

    # 4. PREVIOUSLY DECIDED: ...
    if decided_text:
        out_lines.append(
            f"  {paint('PREVIOUSLY DECIDED:', 'cyan', bold=True)} {decided_text}"
        )

    # 5. SOURCES:
    #      - <url>
    sources = w.get("sources", [])
    if isinstance(sources, list) and sources:
        out_lines.append(f"  {paint('SOURCES:', 'cyan', bold=True)}")
        for u in sources:
            out_lines.append(f"    - {paint(str(u), 'blue')}")

    # 6. (warning text written by: ...)
    if writer_str:
        out_lines.append(paint(writer_str, "dim_grey"))

    return "\n".join(out_lines)

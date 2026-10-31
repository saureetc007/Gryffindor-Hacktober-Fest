"""Markdown report generation for recovered decision records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from decisionlens.models import Claim, DecisionRecord


def write_report(records: list[DecisionRecord], path: str | Path) -> None:
    """Generate and write a Markdown report from recovered DecisionRecords.

    Per decision writes:
    - title
    - status
    - decided
    - rejected ideas with reasons
    - each source as a link plus its verbatim quote and comment id
    - linked code
    - an "Unverified" section from uncertainties

    Args:
        records: List of DecisionRecord objects.
        path: Destination file path for Markdown report.
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not records:
        content = "# DecisionLens Recovery Report\n\nNo decision records found.\n"
        output_path.write_text(content, encoding="utf-8")
        return

    lines: list[str] = [
        "# DecisionLens Recovery Report",
        "",
        f"**Total Decisions Recovered:** {len(records)}",
        "",
        "---",
        "",
    ]

    for idx, rec in enumerate(records, start=1):
        rec_id = rec.id or f"DEC-{idx:03d}"
        lines.append(f"## {idx}. {rec.title or 'Untitled Decision'}")
        lines.append("")
        lines.append(f"- **ID:** `{rec_id}`")
        lines.append(f"- **Status:** `{rec.status}`")
        lines.append(f"- **Decided:** {rec.decided or 'N/A'}")
        if rec.thread_id or rec.thread_url or rec.thread_title:
            t_id = f"#{rec.thread_id}" if rec.thread_id else ""
            t_link = f"[{t_id} {rec.thread_title}]({rec.thread_url})" if rec.thread_url else f"{t_id} {rec.thread_title}"
            lines.append(f"- **Discussion:** {t_link.strip()}")
        lines.append("")

        # Rejected alternatives
        lines.append("### Rejected Alternatives")
        if rec.rejected:
            for rej in rec.rejected:
                if isinstance(rej, dict):
                    idea = rej.get("idea", "Unknown")
                    why = rej.get("why", "No reason provided")
                else:
                    idea = getattr(rej, "idea", "Unknown")
                    why = getattr(rej, "why", "No reason provided")
                lines.append(f"- **{idea}:** {why}")
        else:
            lines.append("- *None recorded.*")
        lines.append("")

        # Linked code
        lines.append("### Linked Code")
        if rec.linked_code:
            for code_path in rec.linked_code:
                lines.append(f"- `{code_path}`")
        else:
            lines.append("- *None identified.*")
        lines.append("")

        # Sources & verbatim quotes
        lines.append("### Sources & Verbatim Quotes")
        if rec.sources:
            for s in rec.sources:
                if isinstance(s, Claim):
                    cid = s.comment_id or "unknown"
                    quote = s.quote or s.exact_quote or ""
                    url = s.url or ""
                elif isinstance(s, dict):
                    cid = s.get("comment_id") or "unknown"
                    quote = s.get("quote") or s.get("exact_quote") or ""
                    url = s.get("url") or ""
                else:
                    cid = getattr(s, "comment_id", "unknown")
                    quote = getattr(s, "quote", "")
                    url = getattr(s, "url", "")

                if url:
                    lines.append(f"- **Comment [`{cid}`]({url}):**")
                else:
                    lines.append(f"- **Comment `{cid}`:**")
                lines.append(f"  > \"{quote}\"")
                lines.append("")
        else:
            lines.append("- *No verified sources linked.*")
            lines.append("")

        # Unverified section
        lines.append("### Unverified Notes")
        if rec.uncertainties:
            for note in rec.uncertainties:
                lines.append(f"- {note}")
        else:
            lines.append("- *All claims and quotes verified against ground truth.*")
        lines.append("")
        lines.append("---")
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")

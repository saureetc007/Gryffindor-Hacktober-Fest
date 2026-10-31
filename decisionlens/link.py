"""Code linking and path extraction for DecisionLens."""

from __future__ import annotations

import re
from typing import Optional

from decisionlens.models import DecisionRecord, Thread

# Matches paths with slashes (e.g. parser/core.c) or bare filenames with known extensions
PATH_PATTERN = re.compile(
    r"\b(?:[a-zA-Z0-9_\.\-]+/)*[a-zA-Z0-9_\.\-]+\.(?:c|h|py|js|ts|rs|go|java|cpp)\b"
    r"|\b[a-zA-Z0-9_\.\-]+(?:/[a-zA-Z0-9_\.\-]+)+\b"
)
# Matches function calls like name()
FUNC_PATTERN = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]*\(\)")


def extract_paths(text: str) -> list[str]:
    """Extract code paths, bare filenames with known extensions, and function names name().

    Args:
        text: Input text to scan.

    Returns:
        List of unique extracted paths and symbols.
    """
    if not text:
        return []

    found: list[str] = []
    seen: set[str] = set()

    for match in PATH_PATTERN.findall(text):
        cleaned = match.strip(".,;:\"'()")
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            found.append(cleaned)

    for match in FUNC_PATTERN.findall(text):
        if match not in seen:
            seen.add(match)
            found.append(match)

    return found


def link_code(
    record: DecisionRecord,
    thread: Thread,
    changed_files: Optional[list[str]] = None,
) -> DecisionRecord:
    """Collect code paths from sources in thread and changed files.

    Paths come from code only, never from the model.

    Args:
        record: DecisionRecord to update.
        thread: Thread containing original comments.
        changed_files: Optional list of files changed in a PR.

    Returns:
        The updated DecisionRecord with linked_code populated.
    """
    linked: list[str] = list(record.linked_code or [])
    seen: set[str] = set(linked)

    # Collect paths from the full text of every comment cited in record.sources
    for src in record.sources:
        cid = getattr(src, "comment_id", "") or (
            src.get("comment_id") if isinstance(src, dict) else ""
        )
        if cid:
            comment = thread.get_comment(cid)
            if comment and comment.text:
                for p in extract_paths(comment.text):
                    if p not in seen:
                        seen.add(p)
                        linked.append(p)

        quote = getattr(src, "quote", "") or (
            src.get("quote") if isinstance(src, dict) else ""
        )
        if quote:
            for p in extract_paths(quote):
                if p not in seen:
                    seen.add(p)
                    linked.append(p)

    if changed_files:
        for cf in changed_files:
            if cf not in seen:
                seen.add(cf)
                linked.append(cf)

    record.linked_code = linked
    return record

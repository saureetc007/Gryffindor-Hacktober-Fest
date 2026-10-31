"""End-to-end learning and persistence pipeline for DecisionLens."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from decisionlens.chunk import chunk_thread
from decisionlens.extract import extract_thread
from decisionlens.ingest import load_thread
from decisionlens.link import link_code
from decisionlens.merge import merge_proposals
from decisionlens.models import Claim, DecisionRecord


def learn(
    thread_path: str | Path,
    llm: Optional[Callable[..., str]] = None,
    existing_records: Optional[list[DecisionRecord]] = None,
) -> list[DecisionRecord]:
    """Run full recovery pipeline on a discussion thread.

    Runs load, chunk, extract_thread, merge_proposals, link_code and returns records.
    If existing_records is provided, assigns non-colliding IDs.

    Args:
        thread_path: Path to thread JSON or text file.
        llm: Callable accepting (prompt, schema).
        existing_records: Optional existing records to avoid ID collisions.

    Returns:
        List of finalized DecisionRecord objects.
    """
    if llm is None:
        from decisionlens.extract import call_gemma

        llm = call_gemma

    thread = load_thread(thread_path)
    chunks = chunk_thread(thread)
    proposals, _ = extract_thread(thread, chunks, llm=llm)
    records, _ = merge_proposals(proposals, thread, llm=llm)
    linked_records = [link_code(rec, thread) for rec in records]

    if existing_records:
        import re

        max_num = 0
        for r in existing_records:
            m = re.search(r"(\d+)", r.id)
            if m:
                max_num = max(max_num, int(m.group(1)))
        for i, rec in enumerate(linked_records, start=max_num + 1):
            rec.id = f"DEC-{i:03d}"

    return linked_records


def save_records(records: list[DecisionRecord], path: str | Path) -> None:
    """Save DecisionRecords to a JSON file.

    Args:
        records: List of DecisionRecord objects.
        path: Output file path.
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data: list[dict[str, Any]] = []
    for rec in records:
        sources_list: list[dict[str, Any]] = []
        for s in rec.sources:
            if isinstance(s, Claim):
                sources_list.append(
                    {
                        "comment_id": s.comment_id,
                        "quote": s.quote,
                        "exact_quote": s.exact_quote,
                        "url": s.url,
                        "claim": s.claim,
                        "verified": s.verified,
                    }
                )
            elif isinstance(s, dict):
                sources_list.append(s)

        rejected_list: list[dict[str, Any]] = []
        for r in rec.rejected:
            if hasattr(r, "to_dict"):
                rejected_list.append(r.to_dict())
            elif isinstance(r, dict):
                rejected_list.append(r)

        data.append(
            {
                "id": rec.id,
                "title": rec.title,
                "decided": rec.decided,
                "rejected": rejected_list,
                "sources": sources_list,
                "linked_code": rec.linked_code,
                "status": rec.status,
                "uncertainties": rec.uncertainties,
                "thread_id": rec.thread_id,
                "thread_title": rec.thread_title,
                "thread_url": rec.thread_url,
            }
        )

    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_records(path: str | Path) -> list[DecisionRecord]:
    """Load DecisionRecords from a JSON file.

    Args:
        path: Input file path.

    Returns:
        List of DecisionRecord instances.
    """
    input_path = Path(path)
    if not input_path.exists():
        return []

    try:
        content = input_path.read_text(encoding="utf-8")
        data = json.loads(content)
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    records: list[DecisionRecord] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        raw_sources = item.get("sources") or []
        sources: list[Claim] = []
        for s in raw_sources:
            if isinstance(s, dict):
                sources.append(
                    Claim(
                        comment_id=str(s.get("comment_id") or ""),
                        quote=str(s.get("quote") or ""),
                        url=str(s.get("url") or ""),
                        exact_quote=str(s.get("exact_quote") or s.get("quote") or ""),
                        claim=str(s.get("claim") or ""),
                        verified=bool(s.get("verified", True)),
                    )
                )

        records.append(
            DecisionRecord(
                id=str(item.get("id") or ""),
                title=str(item.get("title") or ""),
                decided=str(item.get("decided") or ""),
                rejected=item.get("rejected") or [],
                sources=sources,
                linked_code=item.get("linked_code") or [],
                status=str(item.get("status") or "UNRESOLVED"),
                uncertainties=item.get("uncertainties") or [],
                thread_id=str(item.get("thread_id") or ""),
                thread_title=str(item.get("thread_title") or ""),
                thread_url=str(item.get("thread_url") or ""),
            )
        )

    return records

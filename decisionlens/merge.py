"""Decision merging and synthesis using Gemma via Ollama."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from decisionlens.link import extract_paths
from decisionlens.models import Claim, DecisionRecord, DecisionStatus, Thread

MERGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "proposal_indexes": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                    "status": {
                        "type": "string",
                        "enum": ["ACCEPTED", "REJECTED", "UNRESOLVED"],
                    },
                    "decided": {"type": "string"},
                    "rejected": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "idea": {"type": "string"},
                                "why": {"type": "string"},
                            },
                            "required": ["idea", "why"],
                        },
                    },
                    "status_comment_id": {"type": "string"},
                    "status_quote": {"type": "string"},
                },
                "required": [
                    "title",
                    "proposal_indexes",
                    "status",
                    "decided",
                    "rejected",
                    "status_comment_id",
                    "status_quote",
                ],
            },
        }
    },
    "required": ["decisions"],
}

MERGE_PROMPT: str = """You are analyzing verified engineering proposals from discussion threads to synthesize final decision records.
Merge duplicate proposals (those describing the same underlying idea or debate) into cohesive decisions.

Given the numbered proposals below:
For each synthesized decision:
1. "title": Short descriptive title of the decision.
2. "proposal_indexes": List of integer indexes of the proposals merged into this decision.
3. "status": Must be one of "ACCEPTED", "REJECTED", or "UNRESOLVED".
4. "decided": Clear description of what was decided or the consensus outcome.
5. "rejected": List of alternatives that were considered and rejected, each with "idea" and "why".
6. "status_comment_id": Comment ID where the final status or conclusion was stated.
7. "status_quote": A VERBATIM quote from that status comment supporting the outcome.

Never generate URLs or file paths. Code will produce all URLs and file paths.

Output ONLY valid JSON matching this schema:
{
  "decisions": [
    {
      "title": "Retain C implementation for parser",
      "proposal_indexes": [0],
      "status": "REJECTED",
      "decided": "parser/core.c will remain in C; fuzzing and AddressSanitizer added to CI",
      "rejected": [
        {
          "idea": "Rewrite parser/core.c in Rust",
          "why": "2x slower in benchmarks due to slice bounds checks and UTF-8 verification"
        }
      ],
      "status_comment_id": "c8",
      "status_quote": "PR #145 was reverted and parser/core.c will remain implemented in C."
    }
  ]
}

Verified proposals to merge:
{proposals_text}
"""


def _normalize_ws(text: str) -> str:
    """Normalize whitespace and lower-case text for robust quote matching."""
    return " ".join(text.lower().split())


def _fallback_decision_records(
    proposals: list[dict[str, Any]],
    thread: Thread,
    error_note: str,
) -> tuple[list[DecisionRecord], list[str]]:
    """Fallback when model call fails or returns invalid JSON.

    Creates one DecisionRecord per proposal with status UNRESOLVED.
    """
    records: list[DecisionRecord] = []
    uncertainties: list[str] = [error_note]

    for idx, prop in enumerate(proposals):
        title = str(prop.get("name") or f"Proposal {idx}")
        decided = str(prop.get("conclusion") or "")
        sources: list[Claim] = []
        linked_code: list[str] = []

        for claim in prop.get("claims", []):
            cid = str(claim.get("comment_id") or "")
            quote = str(claim.get("quote") or "")
            comment = thread.get_comment(cid)
            url = comment.url if comment else ""
            sources.append(
                Claim(
                    comment_id=cid,
                    quote=quote,
                    url=url,
                    exact_quote=quote,
                    verified=True,
                )
            )
            for path in extract_paths(quote):
                if path not in linked_code:
                    linked_code.append(path)

        note = f"Fallback to UNRESOLVED for proposal {idx}: {error_note}"
        uncertainties.append(note)

        record = DecisionRecord(
            id=f"DEC-{idx + 1:03d}",
            title=title,
            decided=decided,
            rejected=[],
            sources=sources,
            linked_code=linked_code,
            status=DecisionStatus.UNRESOLVED.value,
            uncertainties=[note],
        )
        records.append(record)

    return (records, uncertainties)


def merge_proposals(
    proposals: list[dict[str, Any]],
    thread: Thread,
    llm: Optional[Callable[..., str]] = None,
) -> tuple[list[DecisionRecord], list[str]]:
    """Merge and synthesize verified proposals into DecisionRecords.

    Uses the model to combine duplicates and extract decision outcomes.
    Deterministically verifies the model's answer:
    - proposal_indexes must exist; drops unknown indexes.
    - status_quote must appear in status_comment_id; otherwise downgrades to LOW_CONFIDENCE.
    - sources are built by CODE from verified claims.
    - rejected 'why' must be supported by a verified claim; otherwise marked unverified in uncertainties.

    Args:
        proposals: List of verified proposal dictionaries.
        thread: Thread containing the ground truth comments.
        llm: Callable accepting (prompt, MERGE_SCHEMA). Defaults to call_gemma.

    Returns:
        Tuple of (list of DecisionRecord, uncertainties). Never raises.
    """
    if not proposals:
        return ([], [])

    if llm is None:
        from decisionlens.extract import call_gemma

        llm = call_gemma

    # Build prompt with indexed proposals
    prop_lines = []
    for idx, p in enumerate(proposals):
        name = p.get("name", "Unnamed")
        stance = p.get("stance", "neutral")
        conclusion = p.get("conclusion", "")
        claims_summary = []
        for c in p.get("claims", []):
            cid = c.get("comment_id", "")
            q = c.get("quote", "")
            r = c.get("reason", "")
            claims_summary.append(f"[{cid}] \"{q}\" (Reason: {r})")
        prop_lines.append(
            f"Proposal {idx}: {name}\nStance: {stance}\nConclusion: {conclusion}\nClaims:\n"
            + "\n".join(f"  - {cs}" for cs in claims_summary)
        )

    proposals_text = "\n\n".join(prop_lines)
    prompt = MERGE_PROMPT.replace("{proposals_text}", proposals_text)

    # Call LLM with error handling
    try:
        raw_response = llm(prompt, MERGE_SCHEMA)
    except Exception as e:
        return _fallback_decision_records(
            proposals, thread, f"LLM merge call failed: {e}"
        )

    # Parse JSON safely
    try:
        if isinstance(raw_response, dict):
            data = raw_response
        elif isinstance(raw_response, str):
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                code_lines = cleaned.splitlines()
                if code_lines[0].startswith("```"):
                    code_lines = code_lines[1:]
                if code_lines and code_lines[-1].startswith("```"):
                    code_lines = code_lines[:-1]
                cleaned = "\n".join(code_lines).strip()
            data = json.loads(cleaned)
        else:
            return _fallback_decision_records(
                proposals, thread, "Invalid response type returned by LLM"
            )
    except Exception as e:
        return _fallback_decision_records(
            proposals, thread, f"Invalid JSON returned by LLM: {e}"
        )

    if not isinstance(data, dict) or not isinstance(data.get("decisions"), list):
        return _fallback_decision_records(
            proposals, thread, "Missing 'decisions' array in model response"
        )

    raw_decisions = data["decisions"]
    records: list[DecisionRecord] = []
    uncertainties: list[str] = []

    for d_idx, d in enumerate(raw_decisions, start=1):
        if not isinstance(d, dict):
            uncertainties.append(f"Dropped non-dict decision item {d_idx}")
            continue

        title = str(d.get("title") or f"Decision {d_idx}")
        raw_indexes = d.get("proposal_indexes")

        valid_indexes: list[int] = []
        if isinstance(raw_indexes, list):
            for p_i in raw_indexes:
                if isinstance(p_i, int) and 0 <= p_i < len(proposals):
                    valid_indexes.append(p_i)
                else:
                    uncertainties.append(
                        f"Dropped unknown proposal index {p_i} in decision '{title}'"
                    )

        if not valid_indexes:
            uncertainties.append(
                f"Dropped decision '{title}': no valid proposal_indexes remain"
            )
            continue

        status = str(d.get("status") or "UNRESOLVED").upper()
        if status not in ("ACCEPTED", "REJECTED", "UNRESOLVED", "LOW_CONFIDENCE"):
            status = "UNRESOLVED"

        status_comment_id = str(d.get("status_comment_id") or "")
        status_quote = str(d.get("status_quote") or "")

        # Verify status quote
        status_verified = False
        status_comment = thread.get_comment(status_comment_id)
        if status_comment and status_quote.strip():
            norm_quote = _normalize_ws(status_quote)
            norm_comment = _normalize_ws(status_comment.text)
            if norm_quote in norm_comment:
                status_verified = True

        if status in ("ACCEPTED", "REJECTED"):
            if not status_verified:
                status = DecisionStatus.LOW_CONFIDENCE.value
                uncertainties.append(
                    f"Status quote not found in comment '{status_comment_id}'; downgraded decision '{title}' to LOW_CONFIDENCE: {status_quote!r}"
                )

        decided = str(d.get("decided") or "")

        # Sources are built by CODE from verified claims
        sources: list[Claim] = []
        seen_claims: set[tuple[str, str]] = set()

        for p_idx in valid_indexes:
            prop = proposals[p_idx]
            for claim in prop.get("claims", []):
                cid = str(claim.get("comment_id") or "")
                quote = str(claim.get("quote") or "")
                key = (cid, _normalize_ws(quote))
                if key in seen_claims:
                    continue
                seen_claims.add(key)
                comment = thread.get_comment(cid)
                url = comment.url if comment else ""
                sources.append(
                    Claim(
                        comment_id=cid,
                        quote=quote,
                        url=url,
                        exact_quote=quote,
                        verified=True,
                    )
                )

        if status_verified and status_comment_id and status_quote:
            key = (status_comment_id, _normalize_ws(status_quote))
            if key not in seen_claims:
                seen_claims.add(key)
                c = thread.get_comment(status_comment_id)
                url = c.url if c else ""
                sources.append(
                    Claim(
                        comment_id=status_comment_id,
                        quote=status_quote,
                        url=url,
                        exact_quote=status_quote,
                        verified=True,
                    )
                )

        # Check rejected alternatives
        validated_rejected: list[dict[str, str]] = []
        raw_rejected = d.get("rejected", [])
        if isinstance(raw_rejected, list):
            # Aggregate all claims of the proposals merged into this decision
            merged_claims = []
            for p_idx in valid_indexes:
                merged_claims.extend(proposals[p_idx].get("claims", []))

            for rej_item in raw_rejected:
                if not isinstance(rej_item, dict):
                    continue
                idea = str(rej_item.get("idea") or "")
                why = str(rej_item.get("why") or "")
                if not idea and not why:
                    continue

                # Check if why is supported by verified claims
                why_supported = False
                norm_why = _normalize_ws(why)

                for claim in merged_claims:
                    claim_quote = _normalize_ws(str(claim.get("quote") or ""))
                    claim_reason = _normalize_ws(str(claim.get("reason") or ""))
                    claim_cid = str(claim.get("comment_id") or "")
                    c_obj = thread.get_comment(claim_cid)
                    comment_text = _normalize_ws(c_obj.text) if c_obj else ""

                    if (
                        norm_why in claim_quote
                        or norm_why in claim_reason
                        or claim_reason in norm_why
                        or norm_why in comment_text
                    ):
                        why_supported = True
                        break

                    stop_words = {
                        "a", "an", "the", "in", "on", "of", "to", "for", "with",
                        "is", "was", "it", "and", "or", "by", "that", "this", "be", "as",
                    }
                    why_words = (
                        set(re.findall(r"\b[a-zA-Z0-9_-]+\b", norm_why)) - stop_words
                    )
                    claim_words = (
                        set(
                            re.findall(
                                r"\b[a-zA-Z0-9_-]+\b",
                                claim_quote + " " + claim_reason + " " + comment_text,
                            )
                        )
                        - stop_words
                    )
                    if why_words and len(why_words & claim_words) >= max(
                        1, len(why_words) // 2
                    ):
                        why_supported = True
                        break

                if not why_supported:
                    uncertainties.append(
                        f"Rejected idea '{idea}' reason '{why}' is unverified by claims in decision '{title}'"
                    )

                validated_rejected.append({"idea": idea, "why": why})

        # Extract linked code from sources
        linked_code: list[str] = []
        for src in sources:
            for path in extract_paths(src.quote):
                if path not in linked_code:
                    linked_code.append(path)

        rec = DecisionRecord(
            id=f"DEC-{d_idx:03d}",
            title=title,
            decided=decided,
            rejected=validated_rejected,
            sources=sources,
            linked_code=linked_code,
            status=status,
            uncertainties=list(uncertainties),
        )
        records.append(rec)

    return (records, uncertainties)

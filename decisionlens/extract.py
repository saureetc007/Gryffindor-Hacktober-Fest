"""Decision and proposal extraction using Gemma via Ollama."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from decisionlens.models import Comment, Thread

EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "stance": {
                        "type": "string",
                        "enum": ["supported", "opposed", "neutral"],
                    },
                    "claims": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "comment_id": {"type": "string"},
                                "quote": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                            "required": ["comment_id", "quote", "reason"],
                        },
                    },
                    "conclusion": {"type": "string"},
                },
                "required": ["name", "stance", "claims", "conclusion"],
            },
        }
    },
    "required": ["proposals"],
}

EXTRACT_PROMPT: str = """You are analyzing discussion comments to extract engineering proposals, stances, and decisions.

Read the discussion comments below.
For each proposal:
1. Identify the name of the proposal.
2. Determine whether the consensus stance is "supported", "opposed", or "neutral".
3. Provide the conclusion reached regarding the proposal.
4. For every claim, you MUST provide:
   - "comment_id": The exact ID of the comment (e.g. "c1").
   - "quote": A VERBATIM quote copied exactly word-for-word from that comment text. Do NOT paraphrase or alter the quote.
   - "reason": The technical reasoning or explanation behind the claim.

Never generate URLs or file paths. Code will produce all URLs and paths.

Output ONLY valid JSON matching this schema:
{
  "proposals": [
    {
      "name": "Rewrite parser in Rust",
      "stance": "opposed",
      "claims": [
        {
          "comment_id": "c1",
          "quote": "I propose that we rewrite parser/core.c in Rust.",
          "reason": "Proposed rewrite for memory safety"
        },
        {
          "comment_id": "c5",
          "quote": "The Rust prototype in parser/core.c is 2x slower in benchmarks compared to the C implementation",
          "reason": "Benchmark regression due to bounds checks"
        }
      ],
      "conclusion": "The proposal was rejected and the PR was reverted due to performance regressions."
    }
  ]
}

Comments to analyze:
{comments_text}
"""


def call_gemma(prompt: str, schema: Any = EXTRACT_SCHEMA) -> str:
    """Call gemma4:12b via Ollama with structured output schema.

    Imports ollama inside the function. Never uses closed commercial APIs.
    """
    import ollama
    from decisionlens.config import MODEL_NAME

    kwargs: dict[str, Any] = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0, "num_ctx": 8192},
    }
    if schema is not None:
        kwargs["format"] = schema

    response = ollama.chat(**kwargs)
    return response["message"]["content"]


def extract_chunk(
    chunk: list[Comment],
    llm: Callable[..., str] = call_gemma,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract proposals and claims from a chunk of comments.

    Builds the prompt from the chunk (each comment shown as "[id] author: text"),
    calls llm inside try/except, and parses JSON. Invalid JSON or call errors return
    ([], ["note"]) and never raise.

    Args:
        chunk: List of comments in this window.
        llm: Callable accepting (prompt) or (prompt, schema) and returning a JSON string.

    Returns:
        Tuple of (proposals, uncertainties).
    """
    if not chunk:
        return ([], [])

    lines = [f"[{c.id}] {c.author}: {c.text}" for c in chunk]
    comments_text = "\n\n".join(lines)
    prompt = EXTRACT_PROMPT.replace("{comments_text}", comments_text)

    try:
        raw_response = llm(prompt, EXTRACT_SCHEMA)
    except Exception as e:
        return ([], [f"LLM call failed: {e}"])

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
            return ([], ["Invalid response type returned by LLM"])
    except Exception as e:
        return ([], [f"Invalid JSON returned by LLM: {e}"])

    if not isinstance(data, dict):
        return ([], ["Extracted JSON is not an object"])

    proposals = data.get("proposals")
    if not isinstance(proposals, list):
        return ([], ["Missing 'proposals' array in extracted JSON"])

    return (proposals, [])


def _normalize_ws(text: str) -> str:
    """Normalize whitespace and lower-case text for robust quote matching."""
    return " ".join(text.lower().split())


def verify_quotes(
    proposals: list[dict[str, Any]],
    thread: Thread,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Verify that every claim quote appears verbatim in its referenced comment.

    Keeps a claim only if its quote, whitespace-normalized and case-insensitive,
    appears in the text of the comment with that comment_id in the thread.
    Drops claims with unknown comment ids or failed quotes and records each drop
    in uncertainties. Proposals left with zero claims are dropped too.

    Args:
        proposals: List of proposal dictionaries.
        thread: Thread containing the ground-truth comments.

    Returns:
        Tuple of (verified_proposals, uncertainties).
    """
    comment_map = {c.id: c.text for c in thread.comments}
    verified_proposals: list[dict[str, Any]] = []
    uncertainties: list[str] = []

    for proposal in proposals:
        if not isinstance(proposal, dict):
            uncertainties.append("Dropped non-dict proposal item")
            continue

        prop_name = str(proposal.get("name") or "Unnamed proposal")
        claims = proposal.get("claims")
        if not isinstance(claims, list):
            uncertainties.append(f"Dropped proposal '{prop_name}': claims is not a list")
            continue

        valid_claims: list[dict[str, Any]] = []
        for claim in claims:
            if not isinstance(claim, dict):
                uncertainties.append(f"Dropped non-dict claim in proposal '{prop_name}'")
                continue

            comment_id = str(claim.get("comment_id") or "")
            quote = str(claim.get("quote") or "")

            if not comment_id or comment_id not in comment_map:
                uncertainties.append(
                    f"Dropped claim in proposal '{prop_name}': unknown comment_id '{comment_id}'"
                )
                continue

            if not quote.strip():
                uncertainties.append(
                    f"Dropped claim in comment '{comment_id}': empty quote"
                )
                continue

            comment_text = comment_map[comment_id]
            norm_quote = _normalize_ws(quote)
            norm_comment = _normalize_ws(comment_text)

            if norm_quote in norm_comment:
                valid_claims.append(claim)
            else:
                uncertainties.append(
                    f"Dropped claim in comment '{comment_id}': quote not found in comment text: {quote!r}"
                )

        if valid_claims:
            updated_proposal = dict(proposal)
            updated_proposal["claims"] = valid_claims
            verified_proposals.append(updated_proposal)
        else:
            uncertainties.append(
                f"Dropped proposal '{prop_name}': zero verified claims remaining"
            )

    return (verified_proposals, uncertainties)


def extract_thread(
    thread: Thread,
    chunks: list[list[Comment]],
    llm: Callable[..., str] = call_gemma,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract proposals across all chunks of a thread and verify all quotes.

    Args:
        thread: Ground truth Thread.
        chunks: List of comment chunks.
        llm: Callable returning extracted JSON string.

    Returns:
        Tuple of (verified_proposals, uncertainties).
    """
    combined_proposals: list[dict[str, Any]] = []
    uncertainties: list[str] = []

    for chunk in chunks:
        chunk_props, chunk_uncert = extract_chunk(chunk, llm=llm)
        combined_proposals.extend(chunk_props)
        uncertainties.extend(chunk_uncert)

    verified_props, verify_uncert = verify_quotes(combined_proposals, thread)
    uncertainties.extend(verify_uncert)

    return (verified_props, uncertainties)

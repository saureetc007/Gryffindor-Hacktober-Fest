"""Tests for decision and proposal extraction in DecisionLens."""

import json
from pathlib import Path
import pytest

from decisionlens.chunk import chunk_thread
from decisionlens.extract import (
    EXTRACT_PROMPT,
    EXTRACT_SCHEMA,
    call_gemma,
    extract_chunk,
    extract_thread,
    verify_quotes,
)
from decisionlens.ingest import load_thread
from decisionlens.models import Comment, Thread


@pytest.fixture
def sample_thread() -> Thread:
    sample_path = Path(__file__).parent.parent / "examples" / "sample_thread.json"
    return load_thread(sample_path)


def test_extract_valid_output_is_kept(sample_thread):
    """Verify that proposals with exact quotes from the thread are kept."""
    valid_payload = {
        "proposals": [
            {
                "name": "Rewrite parser in Rust",
                "stance": "opposed",
                "claims": [
                    {
                        "comment_id": "c1",
                        "quote": "I propose that we rewrite parser/core.c in Rust.",
                        "reason": "Proposed for memory safety and buffer overflow mitigation",
                    },
                    {
                        "comment_id": "c5",
                        "quote": "The Rust prototype in parser/core.c is 2x slower in benchmarks compared to the C implementation",
                        "reason": "Benchmark regression due to bounds checking",
                    },
                ],
                "conclusion": "Proposal rejected and PR reverted due to performance regressions.",
            }
        ]
    }

    def fake_llm(prompt, schema=None):
        return json.dumps(valid_payload)

    chunks = chunk_thread(sample_thread, max_chars=4000, overlap=1)
    proposals, uncertainties = extract_chunk(chunks[0], llm=fake_llm)

    assert len(proposals) == 1
    assert len(uncertainties) == 0

    verified_proposals, verify_uncert = verify_quotes(proposals, sample_thread)
    assert len(verified_proposals) == 1
    assert len(verified_proposals[0]["claims"]) == 2
    assert len(verify_uncert) == 0


def test_extract_hallucinated_quote_is_dropped(sample_thread):
    """Verify that a hallucinated quote is dropped, and proposals with 0 claims are dropped."""
    payload_with_hallucination = {
        "proposals": [
            {
                "name": "Rewrite parser in Rust",
                "stance": "opposed",
                "claims": [
                    {
                        "comment_id": "c1",
                        "quote": "I propose that we rewrite parser/core.c in Rust.",
                        "reason": "Valid claim",
                    },
                    {
                        "comment_id": "c1",
                        "quote": "Rust is 100x faster than C in all synthetic tests.",
                        "reason": "Hallucinated claim",
                    },
                ],
                "conclusion": "Test conclusion",
            },
            {
                "name": "Entirely fake proposal",
                "stance": "supported",
                "claims": [
                    {
                        "comment_id": "c2",
                        "quote": "We should rewrite everything in Haskell immediately.",
                        "reason": "Completely made up quote",
                    }
                ],
                "conclusion": "Should be dropped",
            },
        ]
    }

    verified_proposals, uncertainties = verify_quotes(
        payload_with_hallucination["proposals"], sample_thread
    )

    # First proposal kept with only the 1 valid claim
    assert len(verified_proposals) == 1
    assert verified_proposals[0]["name"] == "Rewrite parser in Rust"
    assert len(verified_proposals[0]["claims"]) == 1
    assert verified_proposals[0]["claims"][0]["quote"] == "I propose that we rewrite parser/core.c in Rust."

    # Second proposal dropped because 0 verified claims remain
    assert any("Dropped proposal 'Entirely fake proposal'" in u for u in uncertainties)
    assert any("quote not found in comment text" in u for u in uncertainties)


def test_extract_wrong_comment_id_is_dropped(sample_thread):
    """Verify that a claim referencing a non-existent comment_id is dropped."""
    payload = {
        "proposals": [
            {
                "name": "Proposal with wrong comment id",
                "stance": "neutral",
                "claims": [
                    {
                        "comment_id": "c999",  # Does not exist in sample_thread
                        "quote": "I propose that we rewrite parser/core.c in Rust.",
                        "reason": "Valid quote but wrong comment id",
                    }
                ],
                "conclusion": "Should be dropped",
            }
        ]
    }

    verified_proposals, uncertainties = verify_quotes(payload["proposals"], sample_thread)
    assert len(verified_proposals) == 0
    assert any("unknown comment_id 'c999'" in u for u in uncertainties)
    assert any("zero verified claims remaining" in u for u in uncertainties)


def test_extract_invalid_json_returns_empty_without_crash(sample_thread):
    """Verify that invalid JSON or LLM call errors return ([], [note]) and never raise."""
    chunk = sample_thread.comments[:3]

    # Test 1: Invalid JSON string returned
    def broken_json_llm(prompt, schema=None):
        return "I am not returning JSON! {broken...<xml>"

    proposals, uncertainties = extract_chunk(chunk, llm=broken_json_llm)
    assert proposals == []
    assert len(uncertainties) == 1
    assert "Invalid JSON" in uncertainties[0]

    # Test 2: LLM raises an unexpected exception
    def erroring_llm(prompt, schema=None):
        raise ConnectionError("Ollama daemon unreachable")

    proposals_err, uncertainties_err = extract_chunk(chunk, llm=erroring_llm)
    assert proposals_err == []
    assert len(uncertainties_err) == 1
    assert "LLM call failed" in uncertainties_err[0]


def test_extract_quote_different_spacing_and_case(sample_thread):
    """Verify that whitespace-normalized, case-insensitive quotes still verify."""
    # Ground truth in c1:
    # "I propose that we rewrite parser/core.c in Rust."
    # Alter spacing and casing:
    varied_quote = "   i   PROPOSE that   WE REWRITE parser/core.c   in RUST.  "

    payload = {
        "proposals": [
            {
                "name": "Rewrite proposal",
                "stance": "supported",
                "claims": [
                    {
                        "comment_id": "c1",
                        "quote": varied_quote,
                        "reason": "Case and whitespace variation test",
                    }
                ],
                "conclusion": "Should verify successfully",
            }
        ]
    }

    verified_proposals, uncertainties = verify_quotes(payload["proposals"], sample_thread)

    assert len(verified_proposals) == 1
    assert len(verified_proposals[0]["claims"]) == 1
    assert len(uncertainties) == 0


def test_extract_thread_end_to_end(sample_thread):
    """Verify extract_thread orchestrates chunking, extraction, and verification."""
    payload = {
        "proposals": [
            {
                "name": "Rewrite parser in Rust",
                "stance": "opposed",
                "claims": [
                    {
                        "comment_id": "c8",
                        "quote": "PR #145 was reverted and parser/core.c will remain implemented in C.",
                        "reason": "Consensus to revert",
                    }
                ],
                "conclusion": "Reverted",
            }
        ]
    }

    def fake_llm(prompt, schema=None):
        return json.dumps(payload)

    chunks = chunk_thread(sample_thread, max_chars=3000, overlap=1)
    proposals, uncertainties = extract_thread(sample_thread, chunks, llm=fake_llm)

    assert len(proposals) >= 1
    assert proposals[0]["name"] == "Rewrite parser in Rust"
    assert proposals[0]["claims"][0]["comment_id"] == "c8"


def test_call_gemma_fallback_on_501(monkeypatch):
    """Verify call_gemma falls back to calling chat without format on 501 structured output error."""
    import sys
    import types

    fake_ollama = types.ModuleType("ollama")

    def fake_chat(**kwargs):
        if "format" in kwargs:
            raise RuntimeError("structured output is unavailable (status code: 501)")
        return {"message": {"content": '{"proposals": []}'}}

    fake_ollama.chat = fake_chat
    monkeypatch.setitem(sys.modules, "ollama", fake_ollama)

    result = call_gemma("Test discussion prompt")
    assert result == '{"proposals": []}'


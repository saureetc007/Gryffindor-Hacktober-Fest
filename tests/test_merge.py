"""Tests for decision merging and synthesis in DecisionLens."""

import json
from pathlib import Path
import pytest

from decisionlens.ingest import load_thread
from decisionlens.merge import MERGE_SCHEMA, merge_proposals
from decisionlens.models import DecisionStatus, Thread


@pytest.fixture
def sample_thread() -> Thread:
    sample_path = Path(__file__).parent.parent / "examples" / "sample_thread.json"
    return load_thread(sample_path)


@pytest.fixture
def sample_proposals():
    return [
        {
            "name": "Rewrite parser/core.c in Rust",
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
                    "reason": "2x slower in benchmarks due to slice bounds checks",
                },
                {
                    "comment_id": "c8",
                    "quote": "PR #145 was reverted and parser/core.c will remain implemented in C.",
                    "reason": "Consensus reached to revert PR and retain C",
                },
            ],
            "conclusion": "The proposal was rejected and PR was reverted.",
        }
    ]


def test_merge_clear_rejection(sample_thread, sample_proposals):
    """Test 4a: Clear rejection gives REJECTED with right reason and thread URLs."""
    payload = {
        "decisions": [
            {
                "title": "Retain C implementation for parser/core.c",
                "proposal_indexes": [0],
                "status": "REJECTED",
                "decided": "parser/core.c will remain in C with AddressSanitizer and LibFuzzer in CI",
                "rejected": [
                    {
                        "idea": "Rewrite parser/core.c in Rust",
                        "why": "2x slower in benchmarks compared to C",
                    }
                ],
                "status_comment_id": "c8",
                "status_quote": "PR #145 was reverted and parser/core.c will remain implemented in C.",
            }
        ]
    }

    def fake_llm(prompt, schema=None):
        return json.dumps(payload)

    records, uncertainties = merge_proposals(sample_proposals, sample_thread, llm=fake_llm)

    assert len(records) == 1
    rec = records[0]

    # Verify status
    assert rec.status == DecisionStatus.REJECTED.value

    # Verify rejected alternative
    assert len(rec.rejected) == 1
    assert rec.rejected[0]["idea"] == "Rewrite parser/core.c in Rust"
    assert "2x slower in benchmarks" in rec.rejected[0]["why"]

    # Verify sources built by code with URLs from the thread
    assert len(rec.sources) >= 3
    source_urls = [s.url for s in rec.sources]
    assert all("https://github.com/example-org/fastparser/issues/142#issuecomment-" in u for u in source_urls)
    assert any(s.comment_id == "c1" for s in rec.sources)
    assert any(s.comment_id == "c5" for s in rec.sources)
    assert any(s.comment_id == "c8" for s in rec.sources)

    # Verify linked code was detected
    assert "parser/core.c" in rec.linked_code

    # Reason was verified by claims, so no unverified reason warning
    assert not any("is unverified by claims" in u for u in uncertainties)


def test_merge_hallucinated_status_quote_gives_low_confidence(sample_thread, sample_proposals):
    """Test 4b: A hallucinated status_quote gives LOW_CONFIDENCE."""
    payload = {
        "decisions": [
            {
                "title": "Keep parser in C",
                "proposal_indexes": [0],
                "status": "REJECTED",
                "decided": "parser/core.c will remain in C",
                "rejected": [],
                "status_comment_id": "c8",
                "status_quote": "This quote is completely hallucinated and does not exist in comment c8.",
            }
        ]
    }

    def fake_llm(prompt, schema=None):
        return json.dumps(payload)

    records, uncertainties = merge_proposals(sample_proposals, sample_thread, llm=fake_llm)

    assert len(records) == 1
    assert records[0].status == DecisionStatus.LOW_CONFIDENCE.value
    assert any("downgraded" in u and "LOW_CONFIDENCE" in u for u in uncertainties)


def test_merge_no_conclusion_gives_unresolved(sample_thread, sample_proposals):
    """Test 4c: A thread with no conclusion gives UNRESOLVED."""
    payload = {
        "decisions": [
            {
                "title": "Parser rewrite in Rust discussion",
                "proposal_indexes": [0],
                "status": "UNRESOLVED",
                "decided": "Discussion ongoing; no final consensus reached yet.",
                "rejected": [],
                "status_comment_id": "",
                "status_quote": "",
            }
        ]
    }

    def fake_llm(prompt, schema=None):
        return json.dumps(payload)

    records, uncertainties = merge_proposals(sample_proposals, sample_thread, llm=fake_llm)

    assert len(records) == 1
    assert records[0].status == DecisionStatus.UNRESOLVED.value


def test_merge_invalid_json_fallback(sample_thread, sample_proposals):
    """Test 4d: Invalid JSON falls back to UNRESOLVED without crashing."""
    def broken_llm(prompt, schema=None):
        return "I am not returning valid JSON! { broken ... [["

    records, uncertainties = merge_proposals(sample_proposals, sample_thread, llm=broken_llm)

    # Falls back to 1 record per proposal with UNRESOLVED status
    assert len(records) == len(sample_proposals)
    assert records[0].status == DecisionStatus.UNRESOLVED.value
    assert records[0].title == sample_proposals[0]["name"]
    assert len(records[0].sources) == len(sample_proposals[0]["claims"])
    assert any("Fallback to UNRESOLVED" in u for u in uncertainties)


def test_merge_unknown_proposal_index_is_dropped(sample_thread, sample_proposals):
    """Test 4e: An unknown proposal index is dropped."""
    payload = {
        "decisions": [
            {
                "title": "Decision with mixed indexes",
                "proposal_indexes": [0, 999],  # 0 exists, 999 does not
                "status": "UNRESOLVED",
                "decided": "Some decision",
                "rejected": [],
                "status_comment_id": "",
                "status_quote": "",
            },
            {
                "title": "Decision with only unknown indexes",
                "proposal_indexes": [404, 500],  # Neither exists
                "status": "UNRESOLVED",
                "decided": "Should be completely dropped",
                "rejected": [],
                "status_comment_id": "",
                "status_quote": "",
            },
        ]
    }

    def fake_llm(prompt, schema=None):
        return json.dumps(payload)

    records, uncertainties = merge_proposals(sample_proposals, sample_thread, llm=fake_llm)

    # First decision kept with only proposal index 0
    assert len(records) == 1
    assert records[0].title == "Decision with mixed indexes"

    # Uncertainties record dropped index 999 and dropped second decision
    assert any("Dropped unknown proposal index 999" in u for u in uncertainties)
    assert any("no valid proposal_indexes remain" in u for u in uncertainties)

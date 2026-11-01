"""Tests for link, surface, pipeline, and CLI in DecisionLens."""

import json
from pathlib import Path
import pytest

from decisionlens.__main__ import main
from decisionlens.link import extract_paths, link_code
from decisionlens.models import Claim, DecisionRecord, DecisionStatus, PRContext
from decisionlens.pipeline import learn, load_records, save_records
from decisionlens.surface import build_pr_context, surface


def test_extract_paths():
    """Verify extract_paths extracts file paths, bare filenames, and function calls."""
    text = (
        "We modified parser/core.c and added helper.h. "
        "Also see main.py, lib.rs and call init_parser() then process_data()."
    )
    paths = extract_paths(text)

    assert "parser/core.c" in paths
    assert "helper.h" in paths
    assert "main.py" in paths
    assert "lib.rs" in paths
    assert "init_parser()" in paths
    assert "process_data()" in paths


def test_link_code():
    """Verify link_code gathers paths from cited comment texts and changed files."""
    from decisionlens.models import Comment, Thread

    c1 = Comment(id="c1", text="Look at parser/core.c and call parse_tokens().")
    thread = Thread(id="t1", comments=[c1])

    record = DecisionRecord(
        id="DEC-001",
        title="Test",
        sources=[Claim(comment_id="c1", quote="parser/core.c")],
    )

    updated = link_code(record, thread, changed_files=["src/main.c"])
    assert "parser/core.c" in updated.linked_code
    assert "parse_tokens()" in updated.linked_code
    assert "src/main.c" in updated.linked_code


def test_pr_touching_parser_core_c_matches_decision():
    """Verify a PR touching parser/core.c matches the parser decision (strong match)."""
    record = DecisionRecord(
        id="DEC-001",
        title="Retain C parser",
        status="REJECTED",
        decided="parser/core.c will remain in C",
        linked_code=["parser/core.c"],
        sources=[
            Claim(
                comment_id="c8",
                quote="PR #145 was reverted",
                url="https://github.com/example-org/fastparser/issues/142#issuecomment-1008",
            )
        ],
    )

    pr_context = PRContext(
        pr_number=201,
        title="Port parser/core.c to Rust",
        changed_files=["parser/core.c"],
    )

    warnings = surface(pr_context, [record])

    assert len(warnings) == 1
    w = warnings[0]
    assert w["match_type"] == "strong"
    assert "parser/core.c" in w["warning"] or "parser/core.c" in str(w)
    assert (
        "https://github.com/example-org/fastparser/issues/142#issuecomment-1008"
        in w["sources"]
    )


def test_unrelated_pr_gives_no_warning():
    """Verify an unrelated PR gives no warning."""
    record = DecisionRecord(
        id="DEC-001",
        title="Retain C parser",
        status="REJECTED",
        decided="parser/core.c will remain in C",
        linked_code=["parser/core.c"],
    )

    pr_context = PRContext(
        pr_number=202,
        title="Fix documentation typos",
        changed_files=["docs/readme.md"],
        potential_decision_topics=["documentation", "spelling"],
    )

    warnings = surface(pr_context, [record])
    assert warnings == []


def test_invented_file_is_dropped():
    """Verify invented files in summary, topics, or model warning are dropped."""
    # 1. Dropped in build_pr_context
    pr_data = {
        "pr_number": 50,
        "title": "Update parser",
        "files": ["parser/core.c"],
    }

    def fake_pr_llm(prompt, schema=None):
        return json.dumps(
            {
                "summary": "Touches parser/core.c and also updates invented/secret.py",
                "potential_decision_topics": ["fake/path.js", "parser refactor"],
            }
        )

    pr_ctx = build_pr_context(pr_data, llm=fake_pr_llm)
    # Summary mentioned invented/secret.py so it must be dropped
    assert pr_ctx.summary == ""
    # fake/path.js was dropped from topics, but "parser refactor" kept
    assert "fake/path.js" not in pr_ctx.potential_decision_topics
    assert "parser refactor" in pr_ctx.potential_decision_topics
    assert any("Dropped summary" in u for u in pr_ctx.uncertainties)
    assert any("Dropped topic" in u for u in pr_ctx.uncertainties)

    # 2. Dropped in surface warning
    record = DecisionRecord(
        id="DEC-001",
        title="C parser",
        status="REJECTED",
        decided="Stays C",
        linked_code=["parser/core.c"],
    )

    def fake_warning_llm(prompt, schema=None):
        return json.dumps(
            {
                "warning": "This PR modifies parser/core.c and deletes rogue/untracked.c."
            }
        )

    warnings = surface(pr_ctx, [record], llm=fake_warning_llm)
    assert len(warnings) == 1
    # Model warning named rogue/untracked.c, so it was dropped in favor of the template warning
    assert "rogue/untracked.c" not in warnings[0]["warning"]
    assert "parser/core.c" in warnings[0]["warning"]


def test_model_failure_gives_template_warning():
    """Verify model failure in surface falls back to code template warning."""
    record = DecisionRecord(
        id="DEC-001",
        title="Retain C parser",
        status="REJECTED",
        decided="parser/core.c will remain in C",
        linked_code=["parser/core.c"],
    )

    pr_context = PRContext(
        pr_number=300,
        title="Modify core",
        changed_files=["parser/core.c"],
    )

    def failing_llm(prompt, schema=None):
        raise ConnectionError("Ollama failed")

    warnings = surface(pr_context, [record], llm=failing_llm)
    assert len(warnings) == 1
    assert "PR touches parser/core.c which is tied to past decision" in warnings[0]["warning"]


def test_invalid_json_falls_back_to_facts_only():
    """Verify invalid JSON in build_pr_context falls back to facts-only with used_llm=False."""
    pr_data = {
        "pr_number": 88,
        "title": "Refactor parser",
        "files": ["parser/core.c"],
        "commits": ["sha123456"],
    }

    def broken_llm(prompt, schema=None):
        return "Not valid JSON at all!"

    pr_ctx = build_pr_context(pr_data, llm=broken_llm)
    assert pr_ctx.pr_number == 88
    assert pr_ctx.title == "Refactor parser"
    assert pr_ctx.changed_files == ["parser/core.c"]
    assert pr_ctx.commit_shas == ["sha123456"]
    assert pr_ctx.summary == ""
    assert pr_ctx.potential_decision_topics == []
    assert pr_ctx.used_llm is False
    assert len(pr_ctx.uncertainties) > 0


def test_save_and_load_records(tmp_path):
    """Verify save_records and load_records roundtrip serialization."""
    rec = DecisionRecord(
        id="DEC-001",
        title="Test Record",
        decided="Use SQLite",
        rejected=[{"idea": "MongoDB", "why": "No ACID"}],
        sources=[Claim(comment_id="c1", quote="Use SQLite", url="https://example.com/1")],
        linked_code=["db/sqlite.py"],
        status="ACCEPTED",
        uncertainties=["Minor note"],
    )

    file_path = tmp_path / "decisions.json"
    save_records([rec], file_path)
    loaded = load_records(file_path)

    assert len(loaded) == 1
    assert loaded[0].id == "DEC-001"
    assert loaded[0].title == "Test Record"
    assert loaded[0].decided == "Use SQLite"
    assert loaded[0].status == "ACCEPTED"
    assert len(loaded[0].sources) == 1
    assert loaded[0].sources[0].url == "https://example.com/1"
    assert loaded[0].linked_code == ["db/sqlite.py"]


def test_cli_runs_both_commands(tmp_path, monkeypatch):
    """Verify CLI runs both 'learn' and 'check' commands using a fake LLM."""
    sample_thread_path = Path(__file__).parent.parent / "examples" / "sample_thread.json"
    decisions_path = tmp_path / "decisions.json"
    pr_path = tmp_path / "pr.json"

    pr_data = {
        "pr_number": 146,
        "title": "Try Rust rewrite again",
        "files": ["parser/core.c"],
    }
    pr_path.write_text(json.dumps(pr_data), encoding="utf-8")

    def fake_gemma(prompt, schema=None):
        schema_str = json.dumps(schema) if isinstance(schema, dict) else str(schema)
        if "proposals" in schema_str:
            return json.dumps(
                {
                    "proposals": [
                        {
                            "name": "Rewrite parser in Rust",
                            "stance": "opposed",
                            "claims": [
                                {
                                    "comment_id": "c1",
                                    "quote": "I propose that we rewrite parser/core.c in Rust.",
                                    "reason": "Security proposal",
                                },
                                {
                                    "comment_id": "c8",
                                    "quote": "PR #145 was reverted and parser/core.c will remain implemented in C.",
                                    "reason": "Consensus reached",
                                },
                            ],
                            "conclusion": "Reverted",
                        }
                    ]
                }
            )
        elif "decisions" in schema_str:
            return json.dumps(
                {
                    "decisions": [
                        {
                            "title": "Retain C parser",
                            "proposal_indexes": [0],
                            "status": "REJECTED",
                            "decided": "parser/core.c will remain in C",
                            "rejected": [
                                {
                                    "idea": "Rewrite parser/core.c in Rust",
                                    "why": "Performance regression",
                                }
                            ],
                            "status_comment_id": "c8",
                            "status_quote": "PR #145 was reverted and parser/core.c will remain implemented in C.",
                        }
                    ]
                }
            )
        elif "potential_decision_topics" in schema_str:
            return json.dumps(
                {
                    "summary": "Touches parser/core.c to rewrite it",
                    "potential_decision_topics": ["parser refactor"],
                }
            )
        elif "warning" in schema_str:
            return json.dumps(
                {
                    "warning": "Warning: parser/core.c was previously decided to remain in C."
                }
            )
        return "{}"

    # Route all default LLM calls through fake_gemma
    import decisionlens.extract

    monkeypatch.setattr(decisionlens.extract, "call_gemma", fake_gemma)

    # 1. Run learn command
    main(["learn", str(sample_thread_path), "--out", str(decisions_path)])
    assert decisions_path.exists()
    records = load_records(decisions_path)
    assert len(records) >= 1
    assert "parser/core.c" in records[0].linked_code

    # 2. Run check command
    main(["check", str(pr_path), "--decisions", str(decisions_path)])


def test_importing_main_does_not_run_cli(monkeypatch):
    """Verify importing decisionlens.__main__ does not run the CLI."""
    import importlib
    import decisionlens.__main__

    # Re-importing should not trigger main() or call sys.exit
    importlib.reload(decisionlens.__main__)

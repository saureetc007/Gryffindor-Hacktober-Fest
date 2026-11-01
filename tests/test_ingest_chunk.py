"""Tests for ingest.py and chunk.py in DecisionLens."""

from pathlib import Path
import pytest

from decisionlens.chunk import chunk_thread
from decisionlens.ingest import fetch_github_issue, load_thread
from decisionlens.models import Comment, Thread


def test_load_thread_json():
    """Verify that a valid JSON thread file loads correctly."""
    sample_path = Path(__file__).parent.parent / "examples" / "sample_thread.json"
    thread = load_thread(sample_path)

    assert thread.id == "issue-142"
    assert "parser/core.c" in thread.title
    assert thread.url == "https://github.com/example-org/fastparser/issues/142"
    assert len(thread.comments) == 8

    # Verify first and last comments
    assert thread.comments[0].id == "c1"
    assert thread.comments[0].author == "alex_c"
    assert "parser/core.c" in thread.comments[0].text

    assert thread.comments[-1].id == "c8"
    assert thread.comments[-1].author == "sarah_k"
    assert "reverted" in thread.comments[-1].text

    # Verify all comments have required fields populated
    for comment in thread.comments:
        assert comment.id
        assert comment.author
        assert comment.timestamp
        assert comment.url
        assert comment.text


def test_load_thread_plain_text(tmp_path):
    """Verify plain text files are split on blank lines with stable IDs and parsed headers."""
    text_content = """From: alice
I propose rewriting parser/core.c in Rust.

From: bob
Date: 2026-03-01T10:00:00Z
URL: https://example.com/c2
I have performance concerns.

This is a comment without a header line.
"""
    txt_file = tmp_path / "thread.txt"
    txt_file.write_text(text_content, encoding="utf-8")

    thread = load_thread(txt_file)

    assert len(thread.comments) == 3

    # Stable ids c1, c2, c3
    assert thread.comments[0].id == "c1"
    assert thread.comments[0].author == "alice"
    assert "rewriting parser/core.c" in thread.comments[0].text
    assert thread.comments[0].timestamp == ""

    assert thread.comments[1].id == "c2"
    assert thread.comments[1].author == "bob"
    assert thread.comments[1].timestamp == "2026-03-01T10:00:00Z"
    assert thread.comments[1].url == "https://example.com/c2"
    assert "performance concerns" in thread.comments[1].text

    assert thread.comments[2].id == "c3"
    assert thread.comments[2].author == ""
    assert "without a header" in thread.comments[2].text


def test_load_thread_missing_keys_and_empty_file(tmp_path):
    """Verify missing keys and empty files never crash and populate defaults."""
    # Empty file
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")
    t1 = load_thread(empty_file)
    assert t1.id == ""
    assert t1.comments == []

    # Non-existent file
    t2 = load_thread(tmp_path / "non_existent.json")
    assert t2.comments == []

    # JSON with empty dictionary
    empty_json = tmp_path / "empty.json"
    empty_json.write_text("{}", encoding="utf-8")
    t3 = load_thread(empty_json)
    assert t3.id == ""
    assert t3.title == ""
    assert t3.comments == []

    # JSON with missing comment fields
    partial_json = tmp_path / "partial.json"
    partial_json.write_text(
        '{"title": "Missing fields", "comments": [{}, {"text": "just text"}]}',
        encoding="utf-8",
    )
    t4 = load_thread(partial_json)
    assert t4.title == "Missing fields"
    assert len(t4.comments) == 2
    assert t4.comments[0].id == "c1"
    assert t4.comments[0].author == ""
    assert t4.comments[0].text == ""
    assert t4.comments[1].id == "c2"
    assert t4.comments[1].text == "just text"


def test_fetch_github_issue_fake_http_get():
    """Verify fetch_github_issue with an injectable http_get function."""
    mock_responses = {
        "https://api.github.com/repos/example-org/fastparser/issues/142": {
            "id": 9901,
            "title": "Rewrite parser/core.c in Rust",
            "html_url": "https://github.com/example-org/fastparser/issues/142",
            "body": "Initial proposal description.",
            "user": {"login": "alex_c"},
            "created_at": "2026-03-01T09:00:00Z",
        },
        "https://api.github.com/repos/example-org/fastparser/issues/142/comments": [
            {
                "id": 9902,
                "body": "Benchmark shows 2x slower.",
                "user": {"login": "elena_r"},
                "created_at": "2026-03-01T15:00:00Z",
                "html_url": "https://github.com/example-org/fastparser/issues/142#issuecomment-9902",
            },
            {
                "id": 9903,
                "body": "Consensus reached: reverted.",
                "user": "sarah_k",  # Test string user as fallback
                "created_at": "2026-03-01T19:00:00Z",
                "html_url": "https://github.com/example-org/fastparser/issues/142#issuecomment-9903",
            },
        ],
    }

    def fake_http_get(url: str):
        if url in mock_responses:
            return mock_responses[url]
        raise ValueError(f"Unexpected URL: {url}")

    thread = fetch_github_issue("example-org", "fastparser", 142, http_get=fake_http_get)

    assert thread.id == "9901"
    assert thread.title == "Rewrite parser/core.c in Rust"
    assert thread.url == "https://github.com/example-org/fastparser/issues/142"
    assert len(thread.comments) == 3

    # Issue body comment
    assert thread.comments[0].id == "9901"
    assert thread.comments[0].author == "alex_c"
    assert thread.comments[0].text == "Initial proposal description."

    # First subsequent comment
    assert thread.comments[1].id == "9902"
    assert thread.comments[1].author == "elena_r"
    assert thread.comments[1].text == "Benchmark shows 2x slower."

    # Second subsequent comment
    assert thread.comments[2].id == "9903"
    assert thread.comments[2].author == "sarah_k"
    assert thread.comments[2].text == "Consensus reached: reverted."


def test_fetch_github_issue_missing_keys():
    """Verify fetch_github_issue handles incomplete API responses gracefully."""
    def empty_http_get(url: str):
        if "/comments" in url:
            return [{}]
        return {}

    thread = fetch_github_issue("owner", "repo", 10, http_get=empty_http_get)
    assert thread.id == "10"
    assert thread.title == ""
    assert len(thread.comments) == 1
    assert thread.comments[0].id == "c1"
    assert thread.comments[0].author == ""
    assert thread.comments[0].text == ""


def test_chunk_thread_keeps_ids_and_overlap():
    """Verify chunk_thread preserves comment IDs and creates proper overlap."""
    comments = [
        Comment(id=f"c{i}", author=f"user{i}", text=f"Comment number {i}" + "x" * 80)
        for i in range(1, 8)
    ]
    thread = Thread(id="t1", title="Test Thread", comments=comments)

    # Each comment is ~100 chars. max_chars=300 allows ~3 comments per chunk.
    # overlap=2 means adjacent chunks share 2 comments.
    chunks = chunk_thread(thread, max_chars=300, overlap=2)

    assert len(chunks) >= 3

    for chunk in chunks:
        assert len(chunk) > 0
        # IDs must be preserved
        for c in chunk:
            assert c.id.startswith("c")

    # Check overlap between chunk 0 and chunk 1
    chunk0_ids = [c.id for c in chunks[0]]
    chunk1_ids = [c.id for c in chunks[1]]
    shared = set(chunk0_ids).intersection(set(chunk1_ids))
    assert len(shared) == 2
    assert chunk0_ids[-2:] == chunk1_ids[:2]


def test_chunk_thread_max_chars_and_oversized_comment():
    """Verify chunks never exceed max_chars except for single oversized comments."""
    normal_text = "a" * 200
    oversized_text = "Z" * 1500  # Longer than max_chars (1000)

    comments = [
        Comment(id="c1", text=normal_text),
        Comment(id="c2", text=normal_text),
        Comment(id="c3_oversized", text=oversized_text),
        Comment(id="c4", text=normal_text),
        Comment(id="c5", text=normal_text),
    ]
    thread = Thread(id="t1", comments=comments)

    chunks = chunk_thread(thread, max_chars=1000, overlap=1)

    found_oversized_chunk = False
    for chunk in chunks:
        chunk_len = sum(len(c.text) for c in chunk)
        if len(chunk) == 1 and chunk[0].id == "c3_oversized":
            found_oversized_chunk = True
            assert chunk_len == 1500
        else:
            assert chunk_len <= 1000

    assert found_oversized_chunk


def test_chunk_thread_empty_and_single():
    """Verify chunk_thread on empty threads and single-comment threads."""
    empty_thread = Thread(id="empty", comments=[])
    assert chunk_thread(empty_thread) == []

    single_comment = Comment(id="c1", text="Only one comment")
    single_thread = Thread(id="single", comments=[single_comment])
    chunks = chunk_thread(single_thread)
    assert len(chunks) == 1
    assert len(chunks[0]) == 1
    assert chunks[0][0].id == "c1"

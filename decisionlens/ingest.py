"""Thread ingestion from files and GitHub API for DecisionLens."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Callable, Optional
import urllib.request

from decisionlens.models import Comment, Thread


def load_thread(path: str | Path) -> Thread:
    """Load a discussion thread from a JSON or plain-text file.

    JSON files should provide:
        {"id", "title", "url", "comments": [{"id", "author", "timestamp", "url", "text"}]}

    Plain-text files are split into comments on blank-line-separated blocks.
    If a block starts with a header like 'From: name', it is used as the author.
    Every comment without an id is assigned a stable id (c1, c2, ...).
    Missing fields become "". Never crashes on missing keys or empty files.

    Args:
        path: Path to the JSON or text file.

    Returns:
        A Thread instance containing the parsed comments.
    """
    file_path = Path(path)
    if not file_path.exists() or file_path.stat().st_size == 0:
        return Thread()

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return Thread()

    stripped_content = content.strip()
    if not stripped_content:
        return Thread()

    # Try JSON first
    if stripped_content.startswith("{") or str(path).endswith(".json"):
        try:
            data = json.loads(stripped_content)
            if isinstance(data, dict):
                return _parse_json_thread(data)
        except Exception:
            pass

    # Fall back to plain-text parsing
    return _parse_plain_text_thread(content)


def _parse_json_thread(data: dict[str, Any]) -> Thread:
    """Parse a dictionary into a Thread instance."""
    thread_id = str(data.get("id") or "")
    title = str(data.get("title") or "")
    url = str(data.get("url") or "")
    comments_raw = data.get("comments")

    comments: list[Comment] = []
    if isinstance(comments_raw, list):
        for idx, item in enumerate(comments_raw, start=1):
            if isinstance(item, dict):
                cid = str(item.get("id") or f"c{idx}")
                author = str(item.get("author") or "")
                timestamp = str(item.get("timestamp") or "")
                curl = str(item.get("url") or "")
                text = str(item.get("text") or "")
                comments.append(
                    Comment(
                        id=cid,
                        author=author,
                        timestamp=timestamp,
                        url=curl,
                        text=text,
                    )
                )

    return Thread(id=thread_id, title=title, url=url, comments=comments)


def _parse_plain_text_thread(content: str) -> Thread:
    """Parse plain text into a Thread with blank-line-separated comments."""
    blocks = re.split(r"\n\s*\n", content.strip())
    comments: list[Comment] = []

    for idx, block in enumerate(blocks, start=1):
        block_str = block.strip()
        if not block_str:
            continue

        lines = block_str.splitlines()
        author = ""
        timestamp = ""
        url = ""
        idx_start = 0

        for line in lines:
            line_stripped = line.strip()
            m_from = re.match(r"^from\s*:\s*(.*)$", line_stripped, re.IGNORECASE)
            m_date = re.match(r"^date\s*:\s*(.*)$", line_stripped, re.IGNORECASE)
            m_url = re.match(r"^url\s*:\s*(.*)$", line_stripped, re.IGNORECASE)
            if m_from and not author:
                author = m_from.group(1).strip()
                idx_start += 1
            elif m_date and not timestamp:
                timestamp = m_date.group(1).strip()
                idx_start += 1
            elif m_url and not url:
                url = m_url.group(1).strip()
                idx_start += 1
            else:
                break

        body_lines = lines[idx_start:]
        text = "\n".join(body_lines).strip()
        if not text and not author:
            text = block_str

        comments.append(
            Comment(
                id=f"c{idx}",
                author=author,
                timestamp=timestamp,
                url=url,
                text=text,
            )
        )

    return Thread(id="", title="", url="", comments=comments)


def _default_http_get(url: str) -> Any:
    """Default HTTP GET request returning parsed JSON using urllib."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "DecisionLens",
            "Accept": "application/vnd.github.v3+json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_github_issue(
    owner: str,
    repo: str,
    number: int | str,
    http_get: Optional[Callable[[str], Any]] = None,
) -> Thread:
    """Fetch a GitHub issue and its comments via REST API.

    Uses an injectable http_get function (url -> parsed JSON) so tests can pass
    a fake one without making network requests.

    Comment ids, authors, timestamps, and URLs come from the API data, never from a model.

    Args:
        owner: GitHub repository owner.
        repo: GitHub repository name.
        number: Issue or pull request number.
        http_get: Callable taking a URL and returning parsed JSON.

    Returns:
        A Thread instance containing the issue and all its comments.
    """
    get_fn = http_get or _default_http_get

    issue_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}"
    comments_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments"

    try:
        issue_data = get_fn(issue_url)
    except Exception:
        issue_data = {}

    if not isinstance(issue_data, dict):
        issue_data = {}

    thread_id = str(issue_data.get("id") or number or "")
    title = str(issue_data.get("title") or "")
    url = str(issue_data.get("html_url") or "")

    comments: list[Comment] = []

    # Issue body is the initial comment in the thread
    if "body" in issue_data and issue_data["body"] is not None:
        user_field = issue_data.get("user")
        author = ""
        if isinstance(user_field, dict):
            author = str(user_field.get("login") or "")
        elif isinstance(user_field, str):
            author = user_field

        comments.append(
            Comment(
                id=str(issue_data.get("id") or f"issue-{number}"),
                author=author,
                timestamp=str(issue_data.get("created_at") or ""),
                url=str(issue_data.get("html_url") or ""),
                text=str(issue_data.get("body") or ""),
            )
        )

    # Fetch subsequent comments
    try:
        comments_data = get_fn(comments_url)
    except Exception:
        comments_data = []

    if isinstance(comments_data, list):
        for idx, item in enumerate(comments_data, start=1):
            if isinstance(item, dict):
                user_field = item.get("user")
                author = ""
                if isinstance(user_field, dict):
                    author = str(user_field.get("login") or "")
                elif isinstance(user_field, str):
                    author = user_field

                cid = str(item.get("id") or f"c{idx}")
                timestamp = str(item.get("created_at") or "")
                curl = str(item.get("html_url") or "")
                text = str(item.get("body") or "")

                comments.append(
                    Comment(
                        id=cid,
                        author=author,
                        timestamp=timestamp,
                        url=curl,
                        text=text,
                    )
                )

    return Thread(id=thread_id, title=title, url=url, comments=comments)

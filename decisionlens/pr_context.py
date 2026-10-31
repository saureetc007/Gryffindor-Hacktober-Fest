"""Fact extraction for PR context in DecisionLens."""

from dataclasses import dataclass, field


@dataclass
class PRContext:
    """Container for PR context - stores immutable facts and AI-derived content."""

    pr_number: int = 0
    title: str = ""
    changed_files: list[str] = field(default_factory=list)
    commit_shas: list[str] = field(default_factory=list)
    summary: str = field(default="")
    potential_decision_topics: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    used_llm: bool = False


def extract_facts(pr_data: dict) -> PRContext:
    """Extract immutable facts from PR data using only plain Python.

    Returns the pr_number, title, changed_files and commit_shas.

    Args:
        pr_data: Dictionary containing PR information with optional keys.

    Returns:
        PRContext object with extracted facts. Never crashes on missing keys.
    """
    context = PRContext()

    # Extract PR number (default to 0 if missing)
    context.pr_number = pr_data.get("pr_number", 0)

    # Extract title (default to empty string if missing)
    context.title = pr_data.get("title", "")

    # Extract changed files - defaults to empty list if key is missing or value is None
    changes = pr_data.get("files", [])
    changed_paths = [item.get("path") for item in changes if isinstance(item, dict) and item.get("path")]
    context.changed_files = changed_paths if changed_paths else []

    # Extract commit SHAs - defaults to empty list if key is missing or value is None or empty
    commits = pr_data.get("commits", [])
    context.commit_shas = [commit["sha"] for commit in commits if isinstance(commit, dict) and commit.get("sha")] if commits else []

    return context

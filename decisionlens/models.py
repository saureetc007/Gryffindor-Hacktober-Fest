"""Data models for DecisionLens."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class DecisionStatus(str, Enum):
    """Status of a recovered decision."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNRESOLVED = "UNRESOLVED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


@dataclass
class Comment:
    """A discussion comment from a GitHub issue, pull request, or PEP thread."""

    id: str = ""
    author: str = ""
    timestamp: str = ""
    url: str = ""
    text: str = ""


@dataclass
class Thread:
    """A discussion thread containing multiple comments."""

    id: str = ""
    title: str = ""
    url: str = ""
    comments: list[Comment] = field(default_factory=list)

    def get_comment(self, comment_id: str) -> Optional[Comment]:
        """Find a comment by its id."""
        for comment in self.comments:
            if comment.id == comment_id:
                return comment
        return None


@dataclass
class Claim:
    """A claim or evidence snippet anchored to a specific discussion comment.

    Rule: Every claim needs a verbatim quote and a comment id. Code verifies
    the quote really appears in that comment.
    """

    comment_id: str = ""
    quote: str = ""
    url: str = ""
    claim: str = ""
    exact_quote: str = ""
    verified: bool = False

    def __post_init__(self) -> None:
        if self.quote and not self.exact_quote:
            self.exact_quote = self.quote
        elif self.exact_quote and not self.quote:
            self.quote = self.exact_quote

    def verify_against(self, comment_text: str) -> bool:
        """Verify that the quote appears verbatim in the given comment text."""
        target = self.exact_quote or self.quote
        if target and target in comment_text:
            self.verified = True
            return True
        self.verified = False
        return False


@dataclass
class RejectedAlternative:
    """An alternative option that was considered and rejected."""

    idea: str = ""
    why: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"idea": self.idea, "why": self.why}


@dataclass
class DecisionRecord:
    """A recovered decision record.

    Fields:
        decided: The accepted decision / rationale.
        rejected: List of rejected alternatives with {idea, why}.
        sources: List of source claims (url + exact quote + comment id).
        linked_code: Files or code symbols tied to this decision.
        status: ACCEPTED, REJECTED, UNRESOLVED, LOW_CONFIDENCE.
        uncertainties: Notes on any dropped items or model uncertainties.
    """

    decided: str = ""
    rejected: list[dict[str, Any] | RejectedAlternative] = field(default_factory=list)
    sources: list[Claim | dict[str, Any]] = field(default_factory=list)
    linked_code: list[str] = field(default_factory=list)
    status: str = DecisionStatus.UNRESOLVED.value
    uncertainties: list[str] = field(default_factory=list)
    id: str = ""
    title: str = ""


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

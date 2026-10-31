"""PR context extraction and decision warning surfacing."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from decisionlens.link import extract_paths
from decisionlens.models import DecisionRecord, PRContext

PR_CONTEXT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "potential_decision_topics": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["summary", "potential_decision_topics"],
}

PR_CONTEXT_PROMPT: str = """You are analyzing a pull request to summarize its purpose and list potential decision topics.
Never invent or output any file paths or URLs.

PR Information:
Title: {title}
Changed files: {changed_files}

Output ONLY valid JSON matching this schema:
{
  "summary": "Short 1-2 sentence summary of what this PR does.",
  "potential_decision_topics": ["topic1", "topic2"]
}
"""

SURFACE_WARNING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "warning": {"type": "string"},
    },
    "required": ["warning"],
}

SURFACE_WARNING_PROMPT: str = """Write a concise 2-sentence warning to developers explaining why this PR may touch or conflict with past decision '{title}'.
Status: {status}
Previously decided: {decided}
Allowed file paths: {allowed_files}

Never output any file paths other than the allowed file paths. Never invent URLs.

Output ONLY valid JSON matching this schema:
{
  "warning": "2-sentence warning explanation."
}
"""


class WarningItem(dict):
    """Dictionary representing a decision warning with formatted string display."""

    def __str__(self) -> str:
        sources_str = ", ".join(self.get("sources", []))
        return f"[{self.get('match_type', '').upper()}] {self.get('warning', '')}\nSources: {sources_str}"


def build_pr_context(
    pr_data: dict[str, Any],
    llm: Optional[Callable[..., str]] = None,
) -> PRContext:
    """Extract immutable facts and AI-derived summary and topics for a PR.

    Code extracts pr_number, title, changed_files, and commit_shas.
    Gemma writes only summary and potential_decision_topics.
    Invalid JSON falls back to facts-only with used_llm=False.
    Drops any summary or topic that mentions a file path not in changed_files.

    Args:
        pr_data: Raw PR dictionary.
        llm: Callable accepting (prompt, schema). Defaults to call_gemma.

    Returns:
        PRContext instance.
    """
    if not isinstance(pr_data, dict):
        return PRContext()

    pr_number = int(pr_data.get("pr_number") or pr_data.get("number") or 0)
    title = str(pr_data.get("title") or "")

    changed_files: list[str] = []
    files_raw = pr_data.get("files") or pr_data.get("changed_files") or []
    if isinstance(files_raw, list):
        for f in files_raw:
            if isinstance(f, str):
                changed_files.append(f)
            elif isinstance(f, dict):
                path = f.get("path") or f.get("filename")
                if path and isinstance(path, str):
                    changed_files.append(path)

    commit_shas: list[str] = []
    commits_raw = pr_data.get("commits") or pr_data.get("commit_shas") or []
    if isinstance(commits_raw, list):
        for c in commits_raw:
            if isinstance(c, str):
                commit_shas.append(c)
            elif isinstance(c, dict):
                sha = c.get("sha")
                if sha and isinstance(sha, str):
                    commit_shas.append(sha)

    context = PRContext(
        pr_number=pr_number,
        title=title,
        changed_files=changed_files,
        commit_shas=commit_shas,
        summary="",
        potential_decision_topics=[],
        uncertainties=[],
        used_llm=False,
    )

    if llm is None:
        from decisionlens.extract import call_gemma

        llm = call_gemma

    prompt = (
        PR_CONTEXT_PROMPT.replace("{title}", title).replace(
            "{changed_files}", ", ".join(changed_files)
        )
    )

    try:
        raw_response = llm(prompt, PR_CONTEXT_SCHEMA)
    except Exception as e:
        context.uncertainties.append(f"LLM PR context generation failed: {e}")
        return context

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
            context.uncertainties.append("Invalid response type from LLM")
            return context
    except Exception as e:
        context.uncertainties.append(f"Invalid JSON returned by LLM: {e}")
        return context

    if not isinstance(data, dict):
        context.uncertainties.append("Extracted PR context is not a JSON object")
        return context

    context.used_llm = True
    summary = str(data.get("summary") or "").strip()
    raw_topics = data.get("potential_decision_topics") or []

    # Drop summary if it mentions a file path not in changed_files
    summary_paths = extract_paths(summary)
    summary_invalid = False
    for p in summary_paths:
        if not p.endswith("()"):
            if p not in changed_files and not any(
                cf.endswith("/" + p) for cf in changed_files
            ):
                summary_invalid = True
                context.uncertainties.append(
                    f"Dropped summary: mentions file path '{p}' not in changed_files"
                )
                break

    if not summary_invalid:
        context.summary = summary

    # Drop any topic that mentions a file path not in changed_files
    valid_topics: list[str] = []
    if isinstance(raw_topics, list):
        for t in raw_topics:
            t_str = str(t).strip()
            t_paths = extract_paths(t_str)
            t_invalid = False
            for p in t_paths:
                if not p.endswith("()"):
                    if p not in changed_files and not any(
                        cf.endswith("/" + p) for cf in changed_files
                    ):
                        t_invalid = True
                        context.uncertainties.append(
                            f"Dropped topic '{t_str}': mentions file path '{p}' not in changed_files"
                        )
                        break
            if not t_invalid and t_str:
                valid_topics.append(t_str)

    context.potential_decision_topics = valid_topics
    return context


def surface(
    pr_context: PRContext,
    records: list[DecisionRecord],
    llm: Optional[Callable[..., str]] = None,
) -> list[WarningItem]:
    """Find past decisions relevant to this PR and generate warnings.

    Code identifies candidates by overlap between changed_files and linked_code (strong),
    or topic words (weak, labelled 'possible').
    Gemma may only write a 2-sentence warning for candidates; source links come from code.
    Drops model output naming a file or URL not in the data and uses a template warning.

    Args:
        pr_context: Extracted PR facts and context.
        records: List of recovered DecisionRecord objects.
        llm: Callable accepting (prompt, schema). Defaults to call_gemma.

    Returns:
        List of WarningItem objects.
    """
    if not records:
        return []

    pr_files = set(pr_context.changed_files)
    stop_words = {
        "a", "an", "the", "in", "on", "of", "to", "for", "with",
        "is", "was", "it", "and", "or", "by", "that", "this", "be", "as", "pr", "fix", "add",
    }
    pr_topic_text = (
        pr_context.title
        + " "
        + pr_context.summary
        + " "
        + " ".join(pr_context.potential_decision_topics)
    )
    pr_words = (
        set(re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", pr_topic_text.lower())) - stop_words
    )

    warnings: list[WarningItem] = []

    for record in records:
        rec_paths = set(record.linked_code)

        # Check strong match (file path overlap)
        matched_files = [f for f in pr_files if f in rec_paths or any(
            f.endswith("/" + rp) or rp.endswith("/" + f) for rp in rec_paths
        )]

        match_type = ""
        if matched_files:
            match_type = "strong"
        else:
            # Check weak match (topic words overlap)
            rec_text = (
                record.title
                + " "
                + record.decided
                + " "
                + " ".join(
                    r.get("idea", "") for r in record.rejected if isinstance(r, dict)
                )
            )
            rec_words = (
                set(re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", rec_text.lower()))
                - stop_words
            )
            shared_topics = pr_words & rec_words
            if shared_topics:
                match_type = "possible"

        if not match_type:
            continue

        # Allowed files and URLs for verification
        allowed_files = pr_files | rec_paths
        allowed_urls = {
            getattr(s, "url", "") or (s.get("url") if isinstance(s, dict) else "")
            for s in record.sources
        }
        allowed_urls.discard("")

        # Code-generated template warning
        if match_type == "strong":
            files_str = ", ".join(matched_files)
            template_parts = [
                f"PR touches {files_str} which is tied to past decision '{record.title}'."
            ]
        else:
            topics_str = ", ".join(list(shared_topics)[:3])
            template_parts = [
                f"Possible conflict with past decision '{record.title}' on topic '{topics_str}'."
            ]

        if record.rejected:
            for r in record.rejected:
                idea = getattr(r, "idea", "") or (
                    r.get("idea", "") if isinstance(r, dict) else ""
                )
                why = getattr(r, "why", "") or (
                    r.get("why", "") if isinstance(r, dict) else ""
                )
                idea_str = str(idea).strip().rstrip(".")
                why_str = str(why).strip().rstrip(".")
                if idea_str and why_str:
                    template_parts.append(
                        f"Rejected idea: {idea_str}. Reason: {why_str}."
                    )
                elif idea_str:
                    template_parts.append(f"Rejected idea: {idea_str}.")

        if record.status:
            template_parts.append(f"Status: {record.status}.")

        decided_str = str(record.decided or "").strip().rstrip(".")
        if decided_str:
            template_parts.append(f"Previously decided: {decided_str}.")

        template_warning = " ".join(template_parts)
        final_warning = template_warning
        path_source = "template"

        if llm is not None or "call_gemma" in globals():
            if llm is None:
                from decisionlens.extract import call_gemma

                llm = call_gemma

            prompt = (
                SURFACE_WARNING_PROMPT.replace("{title}", record.title)
                .replace("{status}", record.status)
                .replace("{decided}", record.decided)
                .replace("{allowed_files}", ", ".join(allowed_files))
            )

            try:
                raw_response = llm(prompt, SURFACE_WARNING_SCHEMA)
                if isinstance(raw_response, str):
                    cleaned = raw_response.strip()
                    if cleaned.startswith("```"):
                        lines = cleaned.splitlines()
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].startswith("```"):
                            lines = lines[:-1]
                        cleaned = "\n".join(lines).strip()
                    data = json.loads(cleaned)
                elif isinstance(raw_response, dict):
                    data = raw_response
                else:
                    data = {}

                candidate_text = str(data.get("warning") or "").strip()
                if candidate_text:
                    # Drop output naming a file or URL not in the data
                    paths = extract_paths(candidate_text)
                    invalid = False
                    for p in paths:
                        if not p.endswith("()"):
                            if p not in allowed_files and not any(
                                af.endswith("/" + p) for af in allowed_files
                            ):
                                invalid = True
                                break

                    for url in re.findall(r"https?://[^\s]+", candidate_text):
                        if url not in allowed_urls:
                            invalid = True
                            break

                    if not invalid:
                        final_warning = candidate_text
                        path_source = "model"
            except Exception:
                final_warning = template_warning
                path_source = "template"

        # Never end the text with a double period
        clean_text = final_warning.strip()
        while clean_text.endswith(".."):
            clean_text = clean_text[:-1]

        final_warning = f"{clean_text} (warning text written by: {path_source})"
        while final_warning.endswith(".."):
            final_warning = final_warning[:-1]

        # Source URLs come strictly from code, deduplicated by URL preserving order
        source_urls = [
            getattr(s, "url", "") or (s.get("url") if isinstance(s, dict) else "")
            for s in record.sources
        ]
        source_urls = list(dict.fromkeys(u for u in source_urls if u))

        warnings.append(
            WarningItem(
                {
                    "decision_id": record.id,
                    "title": record.title,
                    "status": record.status,
                    "match_type": match_type,
                    "warning": final_warning,
                    "sources": source_urls,
                    "linked_code": record.linked_code,
                }
            )
        )

    return warnings

"""Chunking logic for discussion threads in DecisionLens."""

from __future__ import annotations

from decisionlens.models import Comment, Thread


def chunk_thread(
    thread: Thread, max_chars: int = 6000, overlap: int = 2
) -> list[list[Comment]]:
    """Chunk a thread's comments into overlapping windows.

    Args:
        thread: Thread instance containing comments.
        max_chars: Maximum character budget per chunk (sum of comment text lengths).
        overlap: Number of comments to overlap between consecutive chunks.

    Returns:
        List of chunks, each chunk being a list of Comment objects.
        A single comment longer than max_chars is placed in its own chunk.
        Never returns an empty chunk.
    """
    if not thread or not thread.comments:
        return []

    comments = thread.comments
    n = len(comments)
    chunks: list[list[Comment]] = []
    i = 0
    prev_was_oversized = False

    while i < n:
        comment = comments[i]
        c_len = len(comment.text or "")

        # A single comment longer than max_chars is its own chunk
        if c_len > max_chars:
            chunks.append([comment])
            i += 1
            prev_was_oversized = True
            continue

        # Regular chunk
        chunk: list[Comment] = []
        current_chars = 0

        # Calculate overlap from preceding comments if previous chunk was not oversized
        if overlap > 0 and i > 0 and not prev_was_oversized:
            start_overlap = max(0, i - overlap)
            candidate_overlap = comments[start_overlap:i]

            overlap_to_add: list[Comment] = []
            overlap_chars = 0
            for cand in reversed(candidate_overlap):
                cand_len = len(cand.text or "")
                # Only include candidate if it fits alongside the current comment
                if overlap_chars + cand_len + c_len <= max_chars:
                    overlap_to_add.append(cand)
                    overlap_chars += cand_len
                else:
                    break

            overlap_to_add.reverse()
            chunk.extend(overlap_to_add)
            current_chars += overlap_chars

        # Add comments starting at i
        while i < n:
            next_comment = comments[i]
            next_len = len(next_comment.text or "")

            if next_len > max_chars:
                # Oversized comment belongs in its own chunk on next iteration
                break

            if current_chars + next_len <= max_chars or not chunk:
                chunk.append(next_comment)
                current_chars += next_len
                i += 1
            else:
                break

        prev_was_oversized = False
        if chunk:
            chunks.append(chunk)

    return chunks

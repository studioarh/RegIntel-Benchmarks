import hashlib
import logging
import re
from difflib import SequenceMatcher
from uuid import UUID

from apps.db.models import DocumentChunk
from apps.schemas.diffing import DocumentDiff, ModifiedPassage

logger = logging.getLogger(__name__)

# Raised from 100k to 2M chars (~800 PDF pages) with hierarchical section pruning
MAX_DIFF_INPUT_CHARS = 2_000_000

_SECTION_BOUNDARY_RE = re.compile(r"(?m)^(?=#{1,4}\s+|[A-Z]{3,8}\s+\d+[A-Z]?\.\d+)")


def calculate_overlap_score(diff_text: str, chunk_text: str) -> float:
    return SequenceMatcher(None, diff_text, chunk_text).quick_ratio()


def _coerce_text(value: str | list[str] | None) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n\n".join(str(item) for item in value)
    return str(value)


def split_into_passages(text: str | list[str] | None) -> list[str]:
    coerced = _coerce_text(text)
    if not coerced:
        return []

    normalized = coerced.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"--- Page \d+ ---", "", normalized)

    passages = [p.strip() for p in re.split(r"\n\s*\n", normalized) if p.strip()]

    if len(passages) <= 1 and "\n" in normalized:
        passages = [line.strip() for line in normalized.split("\n") if line.strip()]

    return passages


def _split_into_keyed_sections(text: str) -> list[tuple[str, str]]:
    """Split a long regulatory document into (section_key, section_body) pairs for tree diffing."""
    matches = list(_SECTION_BOUNDARY_RE.finditer(text))
    if len(matches) < 2:
        return [("__root__", text)]

    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append(("__preamble__", preamble))

    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        first_line = body.split("\n", 1)[0].strip()[:80]
        sections.append((first_line, body))

    return sections


def _diff_passage_lists(
    old_passages: list[str],
    new_passages: list[str],
) -> tuple[list[str], list[str], list[ModifiedPassage]]:
    added_passages: list[str] = []
    removed_passages: list[str] = []
    modified_passages: list[ModifiedPassage] = []

    matcher = SequenceMatcher(None, old_passages, new_passages)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added_passages.extend(new_passages[j1:j2])
        elif tag == "delete":
            removed_passages.extend(old_passages[i1:i2])
        elif tag == "replace":
            before_text = "\n".join(old_passages[i1:i2])
            after_text = "\n".join(new_passages[j1:j2])
            modified_passages.append(
                ModifiedPassage(
                    before=before_text,
                    after=after_text,
                )
            )

    return added_passages, removed_passages, modified_passages


def _locate_changed_spans(new_raw: str, changed_texts: list[str]) -> list[tuple[int, int]]:
    """Compute character offset intervals (start, end) in `new_raw` for all changed passages."""
    if not new_raw or not changed_texts:
        return []

    spans: list[tuple[int, int]] = []
    search_cursor = 0

    for passage in changed_texts:
        if not passage:
            continue
        idx = new_raw.find(passage, search_cursor)
        if idx == -1:
            idx = new_raw.find(passage)
        if idx != -1:
            end_idx = idx + len(passage)
            spans.append((idx, end_idx))
            search_cursor = end_idx
        else:
            # If passage contains joined lines, locate each constituent line
            for line in passage.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                line_idx = new_raw.find(stripped)
                if line_idx != -1:
                    spans.append((line_idx, line_idx + len(stripped)))

    return spans


def calculate_diff(
    previous_document_id: UUID | None,
    previous_document_text: str | list[str] | None,
    new_document_text: str | list[str],
) -> DocumentDiff:

    if not previous_document_id:
        return DocumentDiff(
            previous_document_id=None,
            has_prior_version=False,
            change_detected=False,
            status_message=(
                "No prior version of this document was found in the database "
                "(initial ingestion / Version 1)."
            ),
        )

    old_raw = _coerce_text(previous_document_text)
    new_raw = _coerce_text(new_document_text)

    if old_raw == new_raw:
        return DocumentDiff(
            previous_document_id=previous_document_id,
            has_prior_version=True,
            change_detected=False,
            status_message="Compared against prior version: no text changes detected.",
        )

    was_truncated = False

    if len(old_raw) > MAX_DIFF_INPUT_CHARS or len(new_raw) > MAX_DIFF_INPUT_CHARS:
        was_truncated = True
        logger.warning(
            "Document diff input exceeded MAX_DIFF_INPUT_CHARS (%d). "
            "Truncating inputs for diff computation. "
            "old_doc_len=%d, new_doc_len=%d, max_allowed=%d",
            MAX_DIFF_INPUT_CHARS,
            len(old_raw),
            len(new_raw),
            MAX_DIFF_INPUT_CHARS,
        )
        old_raw = old_raw[:MAX_DIFF_INPUT_CHARS]
        new_raw = new_raw[:MAX_DIFF_INPUT_CHARS]

    # Hierarchical section-tree optimization for large multi-section documents
    old_sections = _split_into_keyed_sections(old_raw)
    new_sections = _split_into_keyed_sections(new_raw)

    if len(old_sections) >= 3 and len(new_sections) >= 3:
        old_hash_map: dict[str, tuple[str, str]] = {}
        for key, body in old_sections:
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            old_hash_map[key] = (digest, body)

        new_hash_map: dict[str, tuple[str, str]] = {}
        for key, body in new_sections:
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            new_hash_map[key] = (digest, body)

        unchanged_keys = {
            k
            for k in (old_hash_map.keys() & new_hash_map.keys())
            if old_hash_map[k][0] == new_hash_map[k][0]
        }

        if unchanged_keys:
            pruned_old_passages: list[str] = []
            for key, body in old_sections:
                if key not in unchanged_keys:
                    pruned_old_passages.extend(split_into_passages(body))

            pruned_new_passages: list[str] = []
            for key, body in new_sections:
                if key not in unchanged_keys:
                    pruned_new_passages.extend(split_into_passages(body))

            added_passages, removed_passages, modified_passages = _diff_passage_lists(
                pruned_old_passages, pruned_new_passages
            )
        else:
            added_passages, removed_passages, modified_passages = _diff_passage_lists(
                split_into_passages(old_raw), split_into_passages(new_raw)
            )
    else:
        added_passages, removed_passages, modified_passages = _diff_passage_lists(
            split_into_passages(old_raw), split_into_passages(new_raw)
        )

    changed_texts = added_passages + [mod.after for mod in modified_passages]
    changed_spans = _locate_changed_spans(new_raw, changed_texts)
    has_changes = bool(added_passages or removed_passages or modified_passages)
    status_msg = (
        f"Changes detected against prior version: "
        f"+{len(added_passages)} added, -{len(removed_passages)} removed, "
        f"~{len(modified_passages)} modified."
        if has_changes
        else "Compared against prior version: no passage-level changes detected."
    )

    return DocumentDiff(
        previous_document_id=previous_document_id,
        has_prior_version=True,
        change_detected=has_changes,
        status_message=status_msg,
        added_passages=added_passages,
        removed_passages=removed_passages,
        modified_passages=modified_passages,
        changed_spans=changed_spans,
        was_truncated=was_truncated,
    )


def _has_boundary_crossing_overlap(chunk_text: str, changed_text: str) -> bool:
    """Detect when a changed passage crosses a chunk boundary."""
    if not chunk_text or not changed_text:
        return False
    if chunk_text in changed_text or changed_text in chunk_text:
        return True

    matcher = SequenceMatcher(None, chunk_text, changed_text)
    longest = matcher.find_longest_match(0, len(chunk_text), 0, len(changed_text))
    min_len = min(len(chunk_text), len(changed_text))
    if min_len == 0:
        return False

    return longest.size >= 40 or (longest.size >= 20 and longest.size / min_len >= 0.6)


def get_relevant_chunks_for_diff(
    diff: DocumentDiff, chunks: list[DocumentChunk]
) -> list[DocumentChunk]:
    """Match document chunks to diff changes using interval intersection and boundary overlap."""
    changed_texts = [
        t for t in (diff.added_passages + [mod.after for mod in diff.modified_passages]) if t
    ]
    if not changed_texts and not diff.changed_spans:
        return []

    selected_chunks: list[DocumentChunk] = []

    for chunk in chunks:
        chunk_text = chunk.text or ""
        if not chunk_text:
            continue

        # 1. Exact substring or boundary-crossing contiguous block overlap
        if any(_has_boundary_crossing_overlap(chunk_text, text) for text in changed_texts):
            selected_chunks.append(chunk)
            continue

        # 2. Character-offset interval intersection (when chunk has real char offsets)
        c_start = getattr(chunk, "char_start", 0) or 0
        c_end = getattr(chunk, "char_end", 0) or 0
        has_real_offsets = c_end > c_start and abs((c_end - c_start) - len(chunk_text)) <= 5

        if has_real_offsets and diff.changed_spans:
            if any(
                max(c_start, span_start) < min(c_end, span_end)
                for span_start, span_end in diff.changed_spans
            ):
                selected_chunks.append(chunk)

    return selected_chunks

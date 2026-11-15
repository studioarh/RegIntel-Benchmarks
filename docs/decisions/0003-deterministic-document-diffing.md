# 0003. Deterministic Document Versioning and Diffing

**Date:** 27 August 2026
**Status:** Accepted

## Context
When a new regulatory document is ingested we need to compare it with a prior version (if any) and record all the specific changes (if any) that were made in the new version ex. any changed deadlines, any new clauses etc. Using LLMs is expensive and non-deterministic which is unreliable in the sensitive financial context.

## Decision
1. **Deterministic Substrate:** We use Python's built-in `difflib` (`SequenceMatcher`) to compare normalized text versions before passing data to downstream LLM nodes.
2. **Structured Output:** The diff engine parses operations into a structured format (`added_passages`, `removed_passages`, `modified_passages`).
3. **Safety Limits:** We enforce a maximum character limit (`MAX_DIFF_INPUT_CHARS = 100_000`) and log a warning if text truncation occurs to prevent performance bottlenecks.
4. **Resilience:** The comparison handles first-time documents, identical documents, and malformed OCR text cleanly without crashing.

## Consequences
- **Positive:** Fast, free, and verifiable change detection that acts as an exact factual reference for the LLM extraction agent.
- **Trade-off:** Very large regulatory texts (>100k chars) are truncated for diffing unless broken down into smaller sub-sections.
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class CitationRelationType(StrEnum):
    AMENDS = "amends"
    SUPERSEDES = "supersedes"
    REFERENCES = "references"
    EXEMPTS = "exempts"


@dataclass(frozen=True)
class StatutoryReference:
    sourcebook: str
    chapter: str
    section: str | None
    rule_number: str | None
    provision_type: str | None
    canonical_code: str
    relation_type: CitationRelationType
    char_offset: int


FCA_SOURCEBOOKS: tuple[str, ...] = (
    "PRIN",
    "SYSC",
    "COND",
    "APER",
    "FIT",
    "FINMAR",
    "TC",
    "GEN",
    "FEES",
    "GENPRU",
    "BIPRU",
    "IFPRU",
    "MIFIDPRU",
    "IPRU",
    "CMCOB",
    "COBS",
    "ICOBS",
    "MCOB",
    "BCOBS",
    "CASS",
    "MAR",
    "SUP",
    "DEPP",
    "DISP",
    "CONRED",
    "COMP",
    "CONC",
    "PROD",
    "ESG",
    "PERG",
    "LR",
    "PRR",
    "DTR",
)

_SOURCEBOOK_ALT = "|".join(FCA_SOURCEBOOKS)

_FCA_RULE_PATTERN = re.compile(
    rf"\b(?P<book>{_SOURCEBOOK_ALT})\s+"
    r"(?P<chapter>\d+[A-Z]?)"
    r"(?:\.(?P<section>\d+[A-Z]?))?"
    r"(?:\.(?P<rule>\d+[A-Z]*?))?"
    r"(?P<ptype>[RGEDC])?"
    r"(?:\(\d+\)|\([a-z]\))*\b"
)

_AMENDMENT_VERBS = re.compile(
    r"\b(amend(?:s|ed|ing|ment)?|revok(?:e|es|ed)|inserts?|inserted|substitut(?:e|es|ed))\b",
    re.IGNORECASE,
)

_SUPERSEDE_VERBS = re.compile(
    r"\b(supersed(?:e|es|ed)|replac(?:e|es|ed|ing))\b",
    re.IGNORECASE,
)

_EXEMPTION_VERBS = re.compile(
    r"\b(exempt(?:s|ed|ion)?|disappl(?:y|ies|ied)|exclud(?:e|es|ed)|waiv(?:e|es|ed))\b",
    re.IGNORECASE,
)


def normalize_rule_code(
    sourcebook: str,
    chapter: str,
    section: str | None = None,
    rule_number: str | None = None,
    provision_type: str | None = None,
) -> str:
    parts = [chapter.upper()]
    if section:
        parts.append(section.upper())
    if rule_number:
        parts.append(rule_number.upper())
    suffix = (provision_type or "").upper()
    return f"{sourcebook.upper()} {'.'.join(parts)}{suffix}"


def extract_primary_rule_code(text: str, section_heading: str | None = None) -> str | None:
    """Identify the primary FCA Handbook rule code defined by a chunk or its section heading."""
    leading_slice = text.lstrip()[:160]
    match = _FCA_RULE_PATTERN.search(leading_slice)
    if match is not None:
        return normalize_rule_code(
            sourcebook=match.group("book"),
            chapter=match.group("chapter"),
            section=match.group("section"),
            rule_number=match.group("rule"),
            provision_type=match.group("ptype"),
        )

    if section_heading:
        heading_match = _FCA_RULE_PATTERN.search(section_heading)
        if heading_match is not None:
            return normalize_rule_code(
                sourcebook=heading_match.group("book"),
                chapter=heading_match.group("chapter"),
                section=heading_match.group("section"),
                rule_number=heading_match.group("rule"),
                provision_type=heading_match.group("ptype"),
            )

    return None


def extract_statutory_references(text: str) -> list[StatutoryReference]:
    """Extract canonical UK FCA Handbook rule references and classify their relation type."""
    if not text:
        return []

    references: list[StatutoryReference] = []
    seen_codes_at_offset: set[tuple[str, int]] = set()

    matches = list(_FCA_RULE_PATTERN.finditer(text))

    for idx, match in enumerate(matches):
        book = match.group("book")
        chapter = match.group("chapter")
        section = match.group("section")
        rule = match.group("rule")
        ptype = match.group("ptype")

        canonical = normalize_rule_code(
            sourcebook=book,
            chapter=chapter,
            section=section,
            rule_number=rule,
            provision_type=ptype,
        )

        key = (canonical, match.start())
        if key in seen_codes_at_offset:
            continue
        seen_codes_at_offset.add(key)

        prev_bound = matches[idx - 1].end() if idx > 0 else 0
        window_start = max(prev_bound, match.start() - 65)
        preceding_context = text[window_start : match.start()]

        # Bound to the current sub-clause (after last comma/semicolon/period if any)
        for sep in (".", ";", ","):
            if sep in preceding_context:
                preceding_context = preceding_context.rsplit(sep, 1)[-1]

        if _SUPERSEDE_VERBS.search(preceding_context):
            relation = CitationRelationType.SUPERSEDES
        elif _AMENDMENT_VERBS.search(preceding_context):
            relation = CitationRelationType.AMENDS
        elif _EXEMPTION_VERBS.search(preceding_context):
            relation = CitationRelationType.EXEMPTS
        else:
            relation = CitationRelationType.REFERENCES

        references.append(
            StatutoryReference(
                sourcebook=book.upper(),
                chapter=chapter.upper(),
                section=section.upper() if section else None,
                rule_number=rule.upper() if rule else None,
                provision_type=ptype.upper() if ptype else None,
                canonical_code=canonical,
                relation_type=relation,
                char_offset=match.start(),
            )
        )

    return references

from src.retrieval.statutory_parser import (
    CitationRelationType,
    extract_primary_rule_code,
    extract_statutory_references,
)


def test_extract_primary_rule_code_from_chunk_and_heading() -> None:
    chunk_text = "CONC 3.3.1AR(2): Firms communicating motor finance promotions must display APR."
    assert extract_primary_rule_code(chunk_text) == "CONC 3.3.1AR"

    fallback_text = "A firm must ensure communications are fair, clear and not misleading."
    assert (
        extract_primary_rule_code(fallback_text, section_heading="PRIN 2A.5 Consumer Understanding")
        == "PRIN 2A.5"
    )
    assert extract_primary_rule_code(fallback_text, section_heading="General Introduction") is None


def test_extract_statutory_references_classifies_relations() -> None:
    passage = (
        "CONC 3.3.1AR amends CONC 3.3.1R to mandate representative APR disclosure, "
        "supersedes DISP 1.6.1G for motor finance commission complaints, "
        "exempts firms from MCOB 3A.2.4R where credit is unsecured, "
        "and operates alongside PRIN 2A.9.4G."
    )

    refs = extract_statutory_references(passage)
    by_code = {r.canonical_code: r for r in refs}

    assert "CONC 3.3.1AR" in by_code
    assert "CONC 3.3.1R" in by_code
    assert by_code["CONC 3.3.1R"].relation_type == CitationRelationType.AMENDS
    assert by_code["DISP 1.6.1G"].relation_type == CitationRelationType.SUPERSEDES
    assert by_code["MCOB 3A.2.4R"].relation_type == CitationRelationType.EXEMPTS
    assert by_code["PRIN 2A.9.4G"].relation_type == CitationRelationType.REFERENCES

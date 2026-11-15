from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session
from src.retrieval.freshness import is_chunk_within_window
from src.retrieval.statutory_parser import extract_statutory_references

from apps.api.app.services.embedding import embed_question


def retrieve_chunks(
    db: Session,
    question: str,
    published_before: date | None = None,
    published_after: date | None = None,
    top_k: int = 10,
    candidate_limit: int = 25,
    rrf_k: int = 60,
    graph_weight: float = 1.15,
) -> list[dict[str, Any]]:

    query = embed_question(question)
    extracted_refs = extract_statutory_references(question)
    query_rule_codes = list({ref.canonical_code for ref in extracted_refs})

    sql = text(
        """
        WITH vector_search AS (
            SELECT
                dc.id,
                GREATEST(0.0, 1.0 - (dc.embedding <=> cast(:embedding as vector))) AS cosine_similarity,
                ROW_NUMBER() OVER (ORDER BY dc.embedding <=> cast(:embedding as vector)) AS rank
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE dc.embedding IS NOT NULL
              AND (cast(:published_before as date) IS NULL OR d.published_at <= cast(:published_before as date))
              AND (cast(:published_after as date) IS NULL OR d.published_at >= cast(:published_after as date))
            ORDER BY dc.embedding <=> cast(:embedding as vector)
            LIMIT :candidate_limit
        ),
        text_search AS (
            SELECT
                dc.id,
                ROW_NUMBER() OVER (
                    ORDER BY ts_rank_cd(to_tsvector('english', dc.text), plainto_tsquery('english', :query_text)) DESC
                ) AS rank
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE to_tsvector('english', dc.text) @@ plainto_tsquery('english', :query_text)
              AND (cast(:published_before as date) IS NULL OR d.published_at <= cast(:published_before as date))
              AND (cast(:published_after as date) IS NULL OR d.published_at >= cast(:published_after as date))
            ORDER BY ts_rank_cd(to_tsvector('english', dc.text), plainto_tsquery('english', :query_text)) DESC
            LIMIT :candidate_limit
        ),
        seed_chunks AS (
            SELECT id, rank AS seed_rank FROM vector_search WHERE rank <= 5
            UNION ALL
            SELECT id, rank AS seed_rank FROM text_search WHERE rank <= 5
        ),
        graph_candidates AS (
            SELECT
                dc.id AS id,
                0 AS hop_priority
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE dc.primary_rule_code IS NOT NULL
              AND dc.primary_rule_code = ANY(cast(:query_rule_codes as text[]))
              AND (cast(:published_before as date) IS NULL OR d.published_at <= cast(:published_before as date))
              AND (cast(:published_after as date) IS NULL OR d.published_at >= cast(:published_after as date))

            UNION ALL

            SELECT
                COALESCE(ccr.target_chunk_id, target_dc.id) AS id,
                MIN(sc.seed_rank) AS hop_priority
            FROM seed_chunks sc
            JOIN chunk_cross_references ccr ON ccr.source_chunk_id = sc.id
            LEFT JOIN document_chunks target_dc ON target_dc.primary_rule_code = ccr.target_rule_code
            JOIN documents d ON d.id = COALESCE(
                (SELECT document_id FROM document_chunks WHERE id = ccr.target_chunk_id),
                target_dc.document_id
            )
            WHERE COALESCE(ccr.target_chunk_id, target_dc.id) IS NOT NULL
              AND (cast(:published_before as date) IS NULL OR d.published_at <= cast(:published_before as date))
              AND (cast(:published_after as date) IS NULL OR d.published_at >= cast(:published_after as date))
            GROUP BY COALESCE(ccr.target_chunk_id, target_dc.id)
        ),
        graph_search AS (
            SELECT
                gc.id,
                ROW_NUMBER() OVER (ORDER BY MIN(gc.hop_priority) ASC) AS rank
            FROM graph_candidates gc
            GROUP BY gc.id
            LIMIT :candidate_limit
        ),
        all_candidate_ids AS (
            SELECT id FROM vector_search
            UNION
            SELECT id FROM text_search
            UNION
            SELECT id FROM graph_search
        ),
        fused AS (
            SELECT
                c.id AS chunk_id,
                COALESCE(v.cosine_similarity, 0.0) AS cosine_similarity,
                COALESCE(1.0 / (:rrf_k + v.rank), 0.0) +
                COALESCE(1.0 / (:rrf_k + t.rank), 0.0) +
                COALESCE(:graph_weight / (:rrf_k + g.rank), 0.0) AS rrf_score
            FROM all_candidate_ids c
            LEFT JOIN vector_search v ON c.id = v.id
            LEFT JOIN text_search t ON c.id = t.id
            LEFT JOIN graph_search g ON c.id = g.id
        )
        SELECT
            dc.id AS chunk_id,
            dc.document_id AS document_id,
            dc.text AS text,
            CASE
                WHEN f.cosine_similarity > 0.0 THEN f.cosine_similarity
                WHEN dc.embedding IS NOT NULL THEN GREATEST(0.0, 1.0 - (dc.embedding <=> cast(:embedding as vector)))
                ELSE 0.0
            END AS similarity,
            f.rrf_score AS rrf_score,
            dc.section_heading AS section_heading,
            dc.page_number AS page_number,
            dc.primary_rule_code AS primary_rule_code,
            dc.table_metadata AS table_metadata,
            d.canonical_url AS url,
            d.title AS title,
            d.published_at AS published_at,
            d.source_type AS document_type
        FROM fused f
        JOIN document_chunks dc ON f.chunk_id = dc.id
        JOIN documents d ON dc.document_id = d.id
        ORDER BY f.rrf_score DESC
        LIMIT :top_k;
    """  # noqa: E501
    )

    result_rows = db.execute(
        sql,
        {
            "embedding": str(query),
            "query_text": question,
            "query_rule_codes": query_rule_codes,
            "candidate_limit": candidate_limit,
            "rrf_k": rrf_k,
            "graph_weight": graph_weight,
            "top_k": top_k,
            "published_before": published_before,
            "published_after": published_after,
        },
    ).all()

    return [
        {
            "chunk_id": str(row.chunk_id),
            "document_id": str(row.document_id),
            "text": row.text,
            "similarity": float(row.similarity),
            "rrf_score": float(getattr(row, "rrf_score", row.similarity)),
            "section_heading": row.section_heading,
            "page_number": row.page_number,
            "primary_rule_code": row.primary_rule_code,
            "table_metadata": row.table_metadata,
            "url": str(row.url),
            "title": row.title,
            "published_at": row.published_at,
            "document_type": row.document_type,
            "is_within_window": is_chunk_within_window(row.published_at, question),
        }
        for row in result_rows
    ]

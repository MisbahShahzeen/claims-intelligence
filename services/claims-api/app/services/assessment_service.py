import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LATEST_ASSESSMENT = text("""
    SELECT id, claim_id, coverage_verdict, coverage_rationale, risk_score,
           risk_band, risk_rationale, recommended_amount, model_version,
           prompt_version, latency_ms, created_at
    FROM ai.assessments
    WHERE claim_id = :claim_id
    ORDER BY created_at DESC
    LIMIT 1
""")

CITATIONS = text("""
    SELECT id, source_type, source_id, source_ref, relevance, quoted_span, supports
    FROM ai.assessment_citations
    WHERE assessment_id = :assessment_id
    ORDER BY supports, relevance DESC NULLS LAST
""")

CLAUSE_BODY = text("""
    SELECT c.clause_text AS body, c.section_ref, c.heading, c.is_exclusion,
           d.title AS document_title
    FROM ai.policy_chunks c
    JOIN ai.policy_documents d ON d.id = c.policy_document_id
    WHERE c.id = :source_id
""")

PRECEDENT_BODY = text("""
    SELECT summary_text AS body, claim_reference, outcome, risk_band,
           claimed_amount, settled_amount, fraud_flag
    FROM ai.claim_precedents
    WHERE id = :source_id
""")


async def latest_for_claim(session: AsyncSession, claim_id: uuid.UUID) -> dict | None:
    row = (
        (await session.execute(LATEST_ASSESSMENT, {"claim_id": str(claim_id)}))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None

    assessment = dict(row)
    citations = (
        (await session.execute(CITATIONS, {"assessment_id": str(assessment["id"])}))
        .mappings()
        .all()
    )
    assessment["citations"] = [dict(citation) for citation in citations]
    return assessment


async def source_detail(
    session: AsyncSession, source_type: str, source_id: uuid.UUID
) -> dict | None:
    """Resolve a citation to its underlying text.

    assessment_citations is polymorphic with no foreign key, so the source_type
    decides which table to read. That is the cost of the polymorphic design,
    and it is paid here in one place rather than spread across callers.
    """
    if source_type == "policy_chunk":
        row = (
            (await session.execute(CLAUSE_BODY, {"source_id": str(source_id)}))
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return {
            "source_type": source_type,
            "source_id": source_id,
            "source_ref": f"Section {row['section_ref']} - {row['heading']}",
            "body": row["body"],
            "metadata": {
                "document_title": row["document_title"],
                "is_exclusion": row["is_exclusion"],
            },
        }

    if source_type == "precedent":
        row = (
            (await session.execute(PRECEDENT_BODY, {"source_id": str(source_id)}))
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return {
            "source_type": source_type,
            "source_id": source_id,
            "source_ref": row["claim_reference"],
            "body": row["body"],
            "metadata": {
                "outcome": row["outcome"],
                "risk_band": row["risk_band"],
                "claimed_amount": str(row["claimed_amount"]),
                "settled_amount": str(row["settled_amount"]) if row["settled_amount"] else None,
                "fraud_flag": row["fraud_flag"],
            },
        }

    return None

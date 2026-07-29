from sqlalchemy import text

CLAIM_CONTEXT = text("""
    SELECT c.id, c.claim_number, c.loss_type, c.loss_date, c.reported_date,
           c.description, c.claimed_amount, c.status,
           p.product_type, p.effective_from, p.effective_to,
           p.coverage_limit, p.deductible
    FROM claims.claims c
    JOIN claims.policies p ON p.id = c.policy_id
    WHERE c.id = :claim_id
""")

CLAIM_EXTRACTIONS = text("""
    SELECT d.filename, d.doc_type, e.extracted, e.confidence
    FROM documents.documents d
    JOIN LATERAL (
        SELECT extracted, confidence
        FROM documents.extractions
        WHERE document_id = d.id AND succeeded
        ORDER BY created_at DESC
        LIMIT 1
    ) e ON true
    WHERE d.claim_id = :claim_id
    ORDER BY d.created_at
""")

CLAIM_EVENT = text("""
    INSERT INTO claims.processed_events (event_id, consumer_group)
    VALUES (:event_id, :consumer_group)
    ON CONFLICT (event_id, consumer_group) DO NOTHING
    RETURNING event_id
""")

INSERT_ASSESSMENT = text("""
    INSERT INTO ai.assessments
        (claim_id, coverage_verdict, coverage_rationale, risk_score, risk_band,
         risk_rationale, recommended_amount, model_version, prompt_version,
         input_tokens, output_tokens, latency_ms)
    VALUES
        (:claim_id, :coverage_verdict, :coverage_rationale, :risk_score, :risk_band,
         :risk_rationale, :recommended_amount, :model_version, :prompt_version,
         :input_tokens, :output_tokens, :latency_ms)
    RETURNING id
""")

INSERT_CITATION = text("""
    INSERT INTO ai.assessment_citations
        (assessment_id, source_type, source_id, source_ref, relevance,
         quoted_span, supports)
    VALUES
        (:assessment_id, :source_type, :source_id, :source_ref, :relevance,
         :quoted_span, :supports)
""")

INSERT_USAGE = text("""
    INSERT INTO ai.ai_usage
        (claim_id, service, operation, model, input_tokens, output_tokens,
         cost_usd, latency_ms, cache_hit, succeeded)
    VALUES
        (:claim_id, 'decision-worker', 'assess', :model, :input_tokens,
         :output_tokens, :cost_usd, :latency_ms, false, :succeeded)
""")

INSERT_OUTBOX = text("""
    INSERT INTO claims.outbox (event_id, event_type, aggregate_type, aggregate_id, envelope)
    VALUES (:event_id, :event_type, :aggregate_type, :aggregate_id, CAST(:envelope AS jsonb))
""")

"""Business and AI-cost metrics, derived from Postgres.

Why query the database rather than instrument the workers directly:

Cost reporting must survive process restarts. In-process counters reset, so
"what did we spend today" would depend on the worker having stayed up - which is
exactly when you most want the number. The durable record is ai.ai_usage, so
that is the source of truth and this exports it.

The tradeoff is staleness: values are as fresh as the poll interval, not
instantaneous. For cost and queue-depth reporting that is the right trade. For
request latency it would not be, which is why the API instruments in-process.

Everything here is a Gauge, not a Counter. These are point-in-time answers to
"what is true now", computed by aggregation. A Counter would imply monotonic
increase-only semantics this data does not have.
"""

import logging
import os
import time

import psycopg
from prometheus_client import Gauge, start_http_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger("metrics-exporter")

DSN = os.environ["POSTGRES_DSN"]
PORT = int(os.environ.get("METRICS_PORT", "9102"))
INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "15"))

ai_cost_usd = Gauge("ai_cost_usd", "Cumulative model spend", ["service", "operation", "model"])
ai_calls = Gauge("ai_calls", "Model calls made", ["service", "operation", "succeeded"])
ai_tokens = Gauge("ai_tokens", "Tokens consumed", ["service", "operation", "direction"])
ai_latency_seconds = Gauge(
    "ai_latency_seconds_avg", "Mean model call latency", ["service", "operation"]
)
ai_cache_hit_ratio = Gauge("ai_cache_hit_ratio", "Fraction of calls served from cache")

ai_cost_per_claim_usd = Gauge(
    "ai_cost_per_claim_usd", "Mean model spend per claim that has been processed"
)
ai_claims_processed = Gauge("ai_claims_processed", "Distinct claims with at least one model call")

claims_by_status = Gauge("claims_by_status", "Claims in each business status", ["status"])
claims_by_risk = Gauge("claims_by_risk_band", "Claims in each risk band", ["risk_band"])
documents_by_status = Gauge(
    "documents_by_processing_status", "Documents in each pipeline state", ["processing_status"]
)
assessments_by_verdict = Gauge(
    "assessments_by_verdict", "Assessments by coverage verdict", ["coverage_verdict"]
)

AI_USAGE = """
    SELECT service, operation, model,
           SUM(cost_usd)                                AS cost,
           SUM(input_tokens)                            AS input_tokens,
           SUM(output_tokens)                           AS output_tokens,
           COUNT(*)                                     AS calls,
           COUNT(*) FILTER (WHERE succeeded)            AS succeeded,
           COUNT(*) FILTER (WHERE NOT succeeded)        AS failed,
           AVG(latency_ms)                              AS avg_latency_ms
    FROM ai.ai_usage
    GROUP BY service, operation, model
"""

CACHE_RATIO = """
    SELECT COALESCE(
        COUNT(*) FILTER (WHERE cache_hit)::float / NULLIF(COUNT(*), 0),
        0
    ) AS ratio
    FROM ai.ai_usage
"""

COST_PER_CLAIM = """
    SELECT COUNT(DISTINCT claim_id)                          AS claims,
           COALESCE(SUM(cost_usd), 0)                        AS total_cost
    FROM ai.ai_usage
    WHERE claim_id IS NOT NULL
"""

SIMPLE_GROUPS = {
    claims_by_status: ("SELECT status AS k, COUNT(*) AS v FROM claims.claims GROUP BY 1", "status"),
    claims_by_risk: (
        "SELECT COALESCE(risk_band, 'unassessed') AS k, COUNT(*) AS v FROM claims.claims GROUP BY 1",
        "risk_band",
    ),
    documents_by_status: (
        "SELECT processing_status AS k, COUNT(*) AS v FROM documents.documents GROUP BY 1",
        "processing_status",
    ),
    assessments_by_verdict: (
        "SELECT coverage_verdict AS k, COUNT(*) AS v FROM ai.assessments GROUP BY 1",
        "coverage_verdict",
    ),
}


def collect(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        # Gauges are cleared before each pass. Without this, a label combination
        # that stops appearing in the data keeps reporting its last value
        # forever - a model you stopped using would look permanently active.
        for gauge in (
            ai_cost_usd, ai_calls, ai_tokens, ai_latency_seconds,
            claims_by_status, claims_by_risk, documents_by_status,
            assessments_by_verdict,
        ):
            gauge.clear()

        cur.execute(AI_USAGE)
        for row in cur.fetchall():
            service, operation, model = row[0], row[1], row[2]
            cost, in_tok, out_tok, _calls, ok, failed, avg_ms = row[3:]

            ai_cost_usd.labels(service, operation, model).set(float(cost or 0))
            ai_tokens.labels(service, operation, "input").set(int(in_tok or 0))
            ai_tokens.labels(service, operation, "output").set(int(out_tok or 0))
            ai_calls.labels(service, operation, "true").set(int(ok or 0))
            ai_calls.labels(service, operation, "false").set(int(failed or 0))
            ai_latency_seconds.labels(service, operation).set(float(avg_ms or 0) / 1000.0)

        cur.execute(CACHE_RATIO)
        ai_cache_hit_ratio.set(float(cur.fetchone()[0]))

        cur.execute(COST_PER_CLAIM)
        claims, total_cost = cur.fetchone()
        claims = int(claims or 0)
        ai_claims_processed.set(claims)
        # Expressed as a ratio of two aggregates rather than an average of
        # per-claim sums: claims differ in document count, and the operational
        # question is total spend divided by total claims.
        ai_cost_per_claim_usd.set(float(total_cost or 0) / claims if claims else 0.0)

        for gauge, (query, label) in SIMPLE_GROUPS.items():
            cur.execute(query)
            for key, value in cur.fetchall():
                gauge.labels(**{label: key}).set(int(value))


def main() -> None:
    start_http_server(PORT)
    logger.info("exporter listening on :%d, polling every %ds", PORT, INTERVAL)

    while True:
        try:
            with psycopg.connect(DSN, connect_timeout=10) as conn:
                collect(conn)
        except Exception:
            # Log and keep polling. A transient database outage should not kill
            # the exporter; Prometheus will show stale values, and the scrape
            # itself still succeeds so "exporter up, data stale" is visible.
            logger.exception("collection failed")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()

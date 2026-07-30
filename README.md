# Claims Intelligence

An event-driven insurance claims platform. Adjusters submit a First Notice of
Loss, upload supporting documents, and receive an advisory coverage assessment
grounded in the governing policy wording and comparable historical claims. Every
conclusion the model reaches is traceable to a specific clause or precedent.

Built as a portfolio project. Everything below runs locally at zero cost.

## What it does

1. A claim is submitted through the FNOL intake endpoint.
2. Documents are uploaded - police reports, repair estimates, invoices.
3. An ingestion worker extracts structured data from each document via Gemini.
4. A decision worker retrieves relevant policy clauses and similar past claims,
   then produces a coverage verdict, a risk score, and citations.
5. The claim is automatically triaged, and connected dashboards update live.
6. An adjuster reviews the assessment, escalates if it exceeds their authority,
   and a senior approves or denies it.

Every status change is authorization-checked and written to an append-only audit
trail.

## Architecture

Four deployable services. The boundary between them is latency shape, not domain
nouns: anything that takes seconds and calls a model sits behind Kafka.

| Service | Responsibility |
|---|---|
| claims-api | REST, JWT auth, WebSocket connections, state machine |
| outbox-relay | Publishes outbox rows to Kafka |
| ingestion-worker | Document extraction via Gemini |
| decision-worker | RAG retrieval and coverage assessment |
| metrics-exporter | Business and AI-cost metrics from Postgres |

Postgres holds three schemas with no cross-schema foreign keys: claims,
documents, and ai. Logical separation with an enforced boundary, so moving a
schema to its own instance is a connection-string change.

## Design decisions worth explaining

**Transactional outbox.** The API writes the claim row and an outbox row in one
transaction; a separate relay publishes to Kafka. This removes the dual-write
problem - an event can never describe a change that rolled back, and a committed
change can never fail to produce an event.

**Two state machines, not one.** The claim status tracks where a human is in
adjudicating a claim. Document extraction and assessment track separately.
Merging them would mean every Kafka retry mutates business state and the audit
trail fills with machine noise.

**Kafka partitioned by aggregate ID.** Ordering is guaranteed within a partition,
so keying on claim_id means a claim's own events can never overtake each other,
while events for different claims process in parallel.

**Idempotent consumers.** Delivery is at-least-once. Every consumer writes the
event ID to processed_events inside the same transaction as its side effect,
which makes redelivery safe and replays free.

**Two vector collections, not one.** Policy wordings are retrieved at clause
granularity - the answer to "is this covered" is a specific exclusion, not a
whole document. Historical claims are retrieved at aggregate granularity, one
embedding per resolved claim. Different retrieval units mean separate tables with
independently tuned HNSW indexes, rather than one search where a clause competes
for top-k against a claim summary.

**Retrieval as evidence attribution, not context compression.** Full extracted
documents still go to the model. Retrieval supplies the set of sources a verdict
is permitted to cite - and citations referencing anything not supplied are
discarded rather than trusted.

**Per-pod Kafka consumer groups.** Each claims-api replica joins a unique group,
so Kafka delivers every event to every replica - which is what makes WebSocket
fanout work across pods with no Redis backplane. Read-model writes use a shared
group name for idempotency, so the side effect still happens once cluster-wide.

**Authority limits and four-eyes approval.** An adjuster cannot approve above
their own authority limit, and an escalated claim cannot be approved by the
person who escalated it. Both are enforced server-side; the Angular UI renders
only the transitions the server says are available.

## Measured results

- Three demo scenarios produce three distinct correct verdicts: a clean claim
  returns covered with a depreciated settlement of 106,362 against 127,971
  claimed; a learner-permit claim returns not covered citing the unlicensed
  driver exclusion; a delayed theft report returns risk 95 citing both the
  notification clause and a fraud-flagged precedent
- AI cost per claim: ~$0.014, of which roughly 74% is the coverage reasoning call
  and 2% is embeddings
- Extraction: ~850 tokens, ~4s per text document
- Assessment: ~5,800 tokens, ~25s including retrieval across both collections
- Publish latency: ~3.8ms mean, outbox row to Kafka
- Embedding cache: 36 embeddings on first seed, 0 API calls on re-seed

## Stack

Python 3.12, FastAPI, SQLAlchemy 2, Alembic, asyncpg. Postgres 16 with pgvector.
Kafka in KRaft mode. Angular 22, TypeScript, RxJS, signals. Gemini 2.5 Flash and
gemini-embedding-001. Prometheus, Grafana. Docker, Kubernetes, GitHub Actions.

## Running it

Infrastructure first:

    docker compose up -d
    docker compose exec postgres psql -U postgres -d claims -c "\dx"

Then migrations and Kafka topics:

    cd services/claims-api && alembic upgrade head
    cd ../outbox-relay && python -m relay.create_topics

Seed the RAG corpus, which needs a Gemini API key in decision-worker/.env:

    cd ../decision-worker && python -m decider.seed

Then each service in its own terminal:

    cd services/claims-api       && uvicorn app.main:app --port 8000
    cd services/outbox-relay     && python -m relay.main
    cd services/ingestion-worker && python -m worker.main
    cd services/decision-worker  && python -m decider.main
    cd frontend/claims-dashboard && npm start

Dashboard at localhost:4200, Grafana at localhost:3000, Kafka UI at
localhost:8080.

Kubernetes manifests are in infra/k8s. Applications run in-cluster; Postgres and
Kafka stay on the host, reached via host.minikube.internal.

## Known gaps

Named deliberately rather than left to be discovered.

- Dead-letter topic is not wired. The topic exists but nothing publishes to it,
  so a permanently unparseable model response retries indefinitely.
- cost_usd reads zero on failed model calls. Token counts are only populated on
  the success path, so the cost dashboard under-reports failures.
- Clause retrieval is a weak signal at this corpus size. Precedent retrieval is
  strong (0.79-0.81 similarity at rank 1, clear margin); clause retrieval returns
  a flat spread because every clause is insurance prose about vehicles. This is
  why coverage reasoning does not depend on retrieval alone.
- Documents use a shared ReadWriteMany volume. Production would use object
  storage; app/core/storage.py exists as the seam for that swap.
- Not production-hardened. Postgres runs on default credentials, Kafka has no
  authentication, there is no TLS, and JWTs cannot be revoked before expiry. All
  appropriate for local development, none appropriate for deployment.

## Architecture decision records

docs/decisions contains two findings worth reading:

- Alembic autogenerate is a draft, not an authority. Four separate failures,
  including one that silently proposed dropping the HNSW vector indexes on every
  subsequent migration.
- The assessment caught inconsistent test data before we did. Twice the model
  identified contradictions between a claim record and its documents that had
  gone unnoticed, and explained which conflicting fact would change the outcome.

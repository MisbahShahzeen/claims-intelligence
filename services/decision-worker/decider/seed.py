"""Populate the two vector collections.

Idempotent by content hash: re-running makes zero embedding API calls once the
cache is warm. That property is verified by running this script twice.

Policy wordings chunk at '###' boundaries, so section_ref survives into the
citation. Precedents embed whole - one vector per resolved claim.
"""

import asyncio
import json
import logging
import re
from datetime import date
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from decider.config import get_settings
from decider.embedder import Embedder, content_hash

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("seed")

settings = get_settings()
SEEDS = Path(__file__).resolve().parent.parent / "seeds"

EXCLUSION_MARKERS = ("exclusion", "shall not be liable", "no claim shall be payable", "excluded")

UPSERT_POLICY_DOC = text("""
    INSERT INTO ai.policy_documents (product_type, title, version, effective_from)
    VALUES (:product_type, :title, :version, :effective_from)
    RETURNING id
""")

FIND_POLICY_DOC = text("""
    SELECT id FROM ai.policy_documents
    WHERE title = :title AND version = :version
""")

INSERT_CHUNK = text("""
    INSERT INTO ai.policy_chunks
        (policy_document_id, section_ref, heading, clause_text, content_hash,
         is_exclusion, ordinal, embedding)
    VALUES
        (:policy_document_id, :section_ref, :heading, :clause_text, :content_hash,
         :is_exclusion, :ordinal, :embedding)
""")

CHUNK_EXISTS = text("SELECT 1 FROM ai.policy_chunks WHERE content_hash = :content_hash")

INSERT_PRECEDENT = text("""
    INSERT INTO ai.claim_precedents
        (claim_reference, product_type, loss_type, summary_text, content_hash,
         outcome, claimed_amount, settled_amount, fraud_flag, risk_band, embedding)
    VALUES
        (:claim_reference, :product_type, :loss_type, :summary_text, :content_hash,
         :outcome, :claimed_amount, :settled_amount, :fraud_flag, :risk_band, :embedding)
""")

PRECEDENT_EXISTS = text(
    "SELECT 1 FROM ai.claim_precedents WHERE content_hash = :content_hash"
)


def parse_wording(markdown: str) -> tuple[str, list[dict]]:
    """Split a wording into clause chunks at '### N.N Heading' boundaries."""
    title_match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "Untitled wording"

    chunks: list[dict] = []
    pattern = re.compile(r"^###\s+([\d.]+)\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(markdown))

    for ordinal, match in enumerate(matches):
        start = match.end()
        end = matches[ordinal + 1].start() if ordinal + 1 < len(matches) else len(markdown)
        body = markdown[start:end].strip()
        if not body:
            continue

        section_ref = match.group(1)
        heading = match.group(2).strip()
        clause_text = f"Section {section_ref} - {heading}\n\n{body}"
        lowered = body.lower()

        chunks.append(
            {
                "section_ref": section_ref,
                "heading": heading,
                "clause_text": clause_text,
                "content_hash": content_hash(clause_text),
                "is_exclusion": any(marker in lowered for marker in EXCLUSION_MARKERS),
                "ordinal": ordinal,
            }
        )

    return title, chunks


async def seed_wording(session, embedder: Embedder, path: Path, product_type: str) -> None:
    title, chunks = parse_wording(path.read_text(encoding="utf-8"))
    logger.info("%s: %d clause(s)", path.name, len(chunks))

    pending = []
    for chunk in chunks:
        exists = await session.execute(
            CHUNK_EXISTS, {"content_hash": chunk["content_hash"]}
        )
        if exists.scalar_one_or_none() is None:
            pending.append(chunk)

    if not pending:
        logger.info("%s: all clauses already indexed", path.name)
        return

    doc_id = await session.scalar(FIND_POLICY_DOC, {"title": title, "version": 3})
    if doc_id is None:
        doc_id = await session.scalar(
            UPSERT_POLICY_DOC,
            {
                "product_type": product_type,
                "title": title,
                "version": 3,
                "effective_from": date(2026, 1, 1),
            },
        )

    batch = await embedder.embed_texts(
        session, [c["clause_text"] for c in pending], task_type="RETRIEVAL_DOCUMENT"
    )
    await embedder.record_usage(session, batch)

    for chunk in pending:
        await session.execute(
            INSERT_CHUNK,
            {
                "policy_document_id": str(doc_id),
                "section_ref": chunk["section_ref"],
                "heading": chunk["heading"],
                "clause_text": chunk["clause_text"],
                "content_hash": chunk["content_hash"],
                "is_exclusion": chunk["is_exclusion"],
                "ordinal": chunk["ordinal"],
                "embedding": str(batch.vectors[chunk["content_hash"]]),
            },
        )

    exclusions = sum(1 for c in pending if c["is_exclusion"])
    logger.info("%s: indexed %d clause(s), %d flagged as exclusions",
                path.name, len(pending), exclusions)


async def seed_precedents(session, embedder: Embedder) -> None:
    records = json.loads((SEEDS / "precedents.json").read_text(encoding="utf-8"))

    pending = []
    for record in records:
        digest = content_hash(record["summary_text"])
        exists = await session.execute(PRECEDENT_EXISTS, {"content_hash": digest})
        if exists.scalar_one_or_none() is None:
            pending.append((digest, record))

    if not pending:
        logger.info("precedents: all already indexed")
        return

    batch = await embedder.embed_texts(
        session, [r["summary_text"] for _d, r in pending], task_type="RETRIEVAL_DOCUMENT"
    )
    await embedder.record_usage(session, batch)

    for digest, record in pending:
        await session.execute(
            INSERT_PRECEDENT,
            {
                "claim_reference": record["claim_reference"],
                "product_type": record["product_type"],
                "loss_type": record["loss_type"],
                "summary_text": record["summary_text"],
                "content_hash": digest,
                "outcome": record["outcome"],
                "claimed_amount": record["claimed_amount"],
                "settled_amount": record["settled_amount"],
                "fraud_flag": record["fraud_flag"],
                "risk_band": record["risk_band"],
                "embedding": str(batch.vectors[digest]),
            },
        )

    logger.info("precedents: indexed %d", len(pending))


async def main() -> None:
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    embedder = Embedder()

    async with sessions() as session:
        async with session.begin():
            await seed_wording(session, embedder, SEEDS / "motor_policy.md", "motor")
            await seed_wording(session, embedder, SEEDS / "property_policy.md", "property")
            await seed_precedents(session, embedder)

    await engine.dispose()
    logger.info("seed complete")


if __name__ == "__main__":
    asyncio.run(main())

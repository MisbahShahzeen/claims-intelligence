"""Evidence retrieval across both collections.

Phase 7 showed that embedding a whole loss narrative and searching policy clauses
gives a weak, flat signal - every clause is insurance prose about vehicles, so
everything matches mildly. The fix is to retrieve per REQUIREMENT rather than per
claim: embed "was the driver licensed", "was notification timely" as separate
queries. Each is short, specific, and lands near the clause that answers it.

Precedents are retrieved once, on the whole narrative, because there the
aggregate-level signal was already strong.

Retrieval is evidence attribution, not context compression. The full extracted
documents still go to the model. What retrieval produces is the set of clauses
and precedents a verdict can cite.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from decider.embedder import Embedder

logger = logging.getLogger("retriever")

# Atomic coverage questions, embedded individually. Each maps to a distinct area
# of the wording, which is what gives retrieval something specific to match.
COVERAGE_REQUIREMENTS = [
    "Is this type of loss covered under the policy scope of cover?",
    "Was the driver holding a valid driving licence at the time of loss?",
    "Was the vehicle being used for a purpose permitted by the policy?",
    "Was the claim notified to the insurer within the required period?",
    "Is a police report or First Information Report required for this loss?",
    "How is the settlement amount calculated, and what deductible applies?",
    "What depreciation applies to replaced parts?",
    "Are there exclusions that would defeat this claim?",
]

SEARCH_CLAUSES = text("""
    SELECT id, section_ref, heading, clause_text, is_exclusion,
           1 - (embedding <=> CAST(:query AS vector)) AS similarity
    FROM ai.policy_chunks
    ORDER BY embedding <=> CAST(:query AS vector)
    LIMIT :limit
""")

SEARCH_PRECEDENTS = text("""
    SELECT id, claim_reference, loss_type, summary_text, outcome,
           claimed_amount, settled_amount, fraud_flag, risk_band,
           1 - (embedding <=> CAST(:query AS vector)) AS similarity
    FROM ai.claim_precedents
    WHERE product_type = :product_type
    ORDER BY embedding <=> CAST(:query AS vector)
    LIMIT :limit
""")


@dataclass(frozen=True)
class ClauseHit:
    id: str
    section_ref: str
    heading: str
    clause_text: str
    is_exclusion: bool
    similarity: float
    requirement: str

    @property
    def source_ref(self) -> str:
        return f"Section {self.section_ref} - {self.heading}"


@dataclass(frozen=True)
class PrecedentHit:
    id: str
    claim_reference: str
    loss_type: str
    summary_text: str
    outcome: str
    claimed_amount: str
    settled_amount: str | None
    fraud_flag: bool
    risk_band: str
    similarity: float

    @property
    def source_ref(self) -> str:
        return self.claim_reference


@dataclass
class Evidence:
    clauses: list[ClauseHit]
    precedents: list[PrecedentHit]
    embedding_api_calls: int
    embedding_tokens: int

    def clause_context(self) -> str:
        if not self.clauses:
            return "No policy clauses retrieved."
        parts = []
        for hit in self.clauses:
            marker = " [EXCLUSION]" if hit.is_exclusion else ""
            parts.append(
                f"[clause:{hit.id}] {hit.source_ref}{marker}\n"
                f"(retrieved for: {hit.requirement})\n{hit.clause_text}"
            )
        return "\n\n---\n\n".join(parts)

    def precedent_context(self) -> str:
        if not self.precedents:
            return "No comparable historical claims found."
        parts = []
        for hit in self.precedents:
            settled = hit.settled_amount or "nil"
            fraud = ", flagged as fraudulent" if hit.fraud_flag else ""
            parts.append(
                f"[precedent:{hit.id}] {hit.claim_reference} "
                f"(outcome: {hit.outcome}, risk: {hit.risk_band}{fraud})\n"
                f"Claimed {hit.claimed_amount}, settled {settled}.\n{hit.summary_text}"
            )
        return "\n\n---\n\n".join(parts)


class Retriever:
    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    async def gather(
        self,
        session: AsyncSession,
        *,
        loss_narrative: str,
        product_type: str,
        per_requirement: int = 2,
        precedent_limit: int = 4,
    ) -> Evidence:
        batch = await self._embedder.embed_texts(
            session,
            [*COVERAGE_REQUIREMENTS, loss_narrative],
            task_type="RETRIEVAL_QUERY",
        )
        await self._embedder.record_usage(session, batch)

        from decider.embedder import content_hash

        seen: dict[str, ClauseHit] = {}
        for requirement in COVERAGE_REQUIREMENTS:
            vector = batch.vectors[content_hash(requirement)]
            result = await session.execute(
                SEARCH_CLAUSES, {"query": str(vector), "limit": per_requirement}
            )
            for row in result:
                key = str(row.id)
                candidate = ClauseHit(
                    id=key,
                    section_ref=row.section_ref,
                    heading=row.heading,
                    clause_text=row.clause_text,
                    is_exclusion=row.is_exclusion,
                    similarity=float(row.similarity),
                    requirement=requirement,
                )
                # A clause matched by two requirements is kept once, attributed
                # to whichever requirement matched it most strongly.
                if key not in seen or candidate.similarity > seen[key].similarity:
                    seen[key] = candidate

        clauses = sorted(seen.values(), key=lambda hit: hit.similarity, reverse=True)

        narrative_vector = batch.vectors[content_hash(loss_narrative)]
        precedent_rows = await session.execute(
            SEARCH_PRECEDENTS,
            {
                "query": str(narrative_vector),
                "product_type": product_type,
                "limit": precedent_limit,
            },
        )
        precedents = [
            PrecedentHit(
                id=str(row.id),
                claim_reference=row.claim_reference,
                loss_type=row.loss_type,
                summary_text=row.summary_text,
                outcome=row.outcome,
                claimed_amount=str(row.claimed_amount),
                settled_amount=str(row.settled_amount) if row.settled_amount else None,
                fraud_flag=row.fraud_flag,
                risk_band=row.risk_band,
                similarity=float(row.similarity),
            )
            for row in precedent_rows
        ]

        logger.info(
            "retrieved %d clause(s) across %d requirement(s), %d precedent(s)",
            len(clauses),
            len(COVERAGE_REQUIREMENTS),
            len(precedents),
        )

        return Evidence(
            clauses=clauses,
            precedents=precedents,
            embedding_api_calls=batch.api_calls,
            embedding_tokens=batch.input_tokens,
        )

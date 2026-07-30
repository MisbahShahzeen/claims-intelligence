"""Coverage and risk assessment via Gemini, grounded in retrieved evidence.

The model receives the full extracted documents AND the retrieved clauses and
precedents. Retrieval is not compressing the context - it is supplying the set of
sources a verdict is permitted to cite. Every citation the model returns must
reference an id that was actually put in front of it, and citations that do not
match are discarded rather than trusted.

This also solves the flat-amounts problem from Phase 6: rather than looking up a
label like "TOTAL" (which breaks on the next document that says "Amount
Payable"), the model reasons over the whole amounts list and states which figure
it treated as the claimable total, and why.
"""

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types

from decider.config import get_settings
from decider.retriever import Evidence

logger = logging.getLogger("assessor")
settings = get_settings()

PROMPT_VERSION = 1
INPUT_USD_PER_MTOK = 0.30
OUTPUT_USD_PER_MTOK = 2.50

VALID_VERDICTS = {"covered", "partially_covered", "not_covered", "indeterminate"}
VALID_BANDS = {"low", "medium", "high"}

SYSTEM_PROMPT = """You are an insurance claims assessment assistant. You produce
an advisory assessment for a human adjuster. You do not make the decision; the
adjuster does.

You are given: the claim record, structured data extracted from its supporting
documents, relevant clauses from the governing policy wording, and comparable
historical claims.

Rules you must follow:

1. Ground every conclusion in the material provided. If the material does not
   settle a question, say so and return "indeterminate" rather than guessing.
2. Cite your sources. Every clause or precedent that materially supports a
   conclusion must appear in the citations array, using the exact id given in
   square brackets, e.g. [clause:abc-123] means id "abc-123".
3. Never invent a clause, a precedent, an amount, or a fact. If a document does
   not state something, it is not evidence.
4. When identifying the claimable amount, reason over the full list of amounts
   rather than trusting any single label. State which figure you treated as the
   claimable total and why. Note explicitly if the documented total differs
   materially from the amount the claimant asked for.
5. Risk scoring reflects the probability that this claim requires closer
   scrutiny - inconsistency between documents, timing that conflicts with policy
   conditions, resemblance to historical claims that were denied or flagged. A
   large but well-evidenced claim is not high risk merely for being large.
6. Write for an adjuster who will read this in fifteen seconds. Be specific and
   brief. No hedging language, no restating the inputs.

Return ONLY a JSON object, no markdown fences:

{
  "coverage_verdict": "covered" | "partially_covered" | "not_covered" | "indeterminate",
  "coverage_rationale": "2-4 sentences. Name the clauses that decide it.",
  "risk_score": integer 0-100,
  "risk_band": "low" | "medium" | "high",
  "risk_rationale": "2-4 sentences. Name what drives the score.",
  "recommended_amount": numeric string or null,
  "amount_reasoning": "one sentence on which figure you used and why",
  "open_questions": ["specific things the adjuster should verify, max 3"],
  "citations": [
    {
      "source": "clause:<id>" or "precedent:<id>",
      "supports": "coverage" | "risk" | "amount",
      "quoted_span": "under 25 words, quoted exactly from the source",
      "relevance": 0.0-1.0
    }
  ]
}"""


@dataclass
class AssessmentResult:
    succeeded: bool
    latency_ms: int
    model: str = settings.gemini_model
    prompt_version: int = PROMPT_VERSION
    input_tokens: int = 0
    output_tokens: int = 0
    payload: dict[str, Any] | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @property
    def cost_usd(self) -> float:
        return (
            self.input_tokens / 1_000_000 * INPUT_USD_PER_MTOK
            + self.output_tokens / 1_000_000 * OUTPUT_USD_PER_MTOK
        )


class Assessor:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)

    async def assess(
        self,
        *,
        claim: dict[str, Any],
        extractions: list[dict[str, Any]],
        evidence: Evidence,
    ) -> AssessmentResult:
        started = time.perf_counter()
        prompt = self._build_prompt(claim, extractions, evidence)
        valid_ids = {f"clause:{hit.id}" for hit in evidence.clauses}
        valid_ids |= {f"precedent:{hit.id}" for hit in evidence.precedents}

        last_error = "unknown error"
        # Token counts are captured outside the try so a response that arrives
        # and then fails validation still reports what it cost. A failed call is
        # not a free call, and a cost dashboard that only counts successes
        # understates spend precisely when spend is being wasted.
        spent_input = 0
        spent_output = 0

        for attempt in range(1, settings.max_retries + 1):
            try:
                response = await asyncio.to_thread(self._call, prompt)
                usage = response.usage_metadata
                spent_input += getattr(usage, "prompt_token_count", 0) or 0
                spent_output += getattr(usage, "candidates_token_count", 0) or 0
                payload = self._parse(response.text)
                self._validate(payload)
                citations = self._filter_citations(payload.get("citations", []), valid_ids)

                return AssessmentResult(
                    succeeded=True,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    input_tokens=spent_input,
                    output_tokens=spent_output,
                    payload=payload,
                    citations=citations,
                )
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"
                retriable = isinstance(error, (json.JSONDecodeError, ValueError)) or any(
                    marker in str(error).lower()
                    for marker in ("429", "resource_exhausted", "503", "unavailable", "timeout")
                )
                if not retriable or attempt == settings.max_retries:
                    break
                delay = min(2**attempt, 30) + random.uniform(0, 1)
                logger.warning(
                    "assess attempt %d failed (%s), retrying in %.1fs", attempt, last_error, delay
                )
                await asyncio.sleep(delay)

        return AssessmentResult(
            succeeded=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
            input_tokens=spent_input,
            output_tokens=spent_output,
            error=last_error,
        )

    def _build_prompt(
        self,
        claim: dict[str, Any],
        extractions: list[dict[str, Any]],
        evidence: Evidence,
    ) -> str:
        documents = (
            json.dumps(extractions, indent=2)
            if extractions
            else "No documents have been extracted for this claim yet."
        )
        return f"""## CLAIM RECORD

Claim number: {claim["claim_number"]}
Product: {claim["product_type"]}
Loss type: {claim["loss_type"]}
Date of loss: {claim["loss_date"]}
Reported: {claim["reported_date"]}
Amount claimed: {claim["claimed_amount"]}
Policy period: {claim["effective_from"]} to {claim["effective_to"]}
Policy coverage limit: {claim["coverage_limit"]}
Policy deductible: {claim["deductible"]}

Description as reported:
{claim["description"]}

## EXTRACTED DOCUMENT DATA

{documents}

## RELEVANT POLICY CLAUSES

{evidence.clause_context()}

## COMPARABLE HISTORICAL CLAIMS

{evidence.precedent_context()}

## TASK

Assess coverage and risk for this claim. Cite only the ids given above."""

    def _call(self, prompt: str):
        return self._client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.1,
                max_output_tokens=8192,
            ),
        )

    @staticmethod
    def _parse(raw: str | None) -> dict[str, Any]:
        if not raw:
            raise ValueError("Model returned an empty response")
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error(
                "unparseable response (%d chars), tail: %r",
                len(cleaned),
                cleaned[-400:],
            )
            raise

    @staticmethod
    def _validate(payload: dict[str, Any]) -> None:
        verdict = payload.get("coverage_verdict")
        if verdict not in VALID_VERDICTS:
            raise ValueError(f"Invalid coverage_verdict: {verdict!r}")
        band = payload.get("risk_band")
        if band not in VALID_BANDS:
            raise ValueError(f"Invalid risk_band: {band!r}")
        score = payload.get("risk_score")
        if not isinstance(score, (int, float)) or not 0 <= score <= 100:
            raise ValueError(f"Invalid risk_score: {score!r}")
        if not payload.get("coverage_rationale"):
            raise ValueError("Missing coverage_rationale")

    @staticmethod
    def _filter_citations(
        citations: list[dict[str, Any]], valid_ids: set[str]
    ) -> list[dict[str, Any]]:
        """Discard citations to sources that were never supplied.

        A hallucinated citation is worse than no citation: it looks like
        evidence. Dropping unmatched ids means every stored citation is
        traceable to a real row.
        """
        kept, dropped = [], []
        for citation in citations:
            source = str(citation.get("source", ""))
            if source in valid_ids:
                kept.append(citation)
            else:
                dropped.append(source)
        if dropped:
            logger.warning("discarded %d unmatched citation(s): %s", len(dropped), dropped)
        return kept

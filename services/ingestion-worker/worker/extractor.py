"""Gemini document extraction with backoff and usage accounting."""

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types

from worker.config import get_settings

logger = logging.getLogger("extractor")
settings = get_settings()

INPUT_USD_PER_MTOK = 0.30
OUTPUT_USD_PER_MTOK = 2.50

SYSTEM_PROMPT = """You extract structured data from insurance claim documents.

Return ONLY a JSON object, no markdown fences, no commentary. Use this shape:

{
  "doc_type": one of "police_report" | "invoice" | "medical_bill" | "repair_estimate" | "photo" | "other",
  "summary": one sentence, under 200 characters,
  "parties": [names of people or organisations mentioned],
  "dates": [ISO-8601 dates found, e.g. "2026-05-14"],
  "amounts": [{"label": what the amount is for, "value": numeric string, "currency": ISO code}],
  "identifiers": [{"kind": e.g. "vehicle_registration" | "fir_number" | "policy_number", "value": string}],
  "key_facts": [up to 5 short factual statements from the document],
  "confidence": a number between 0 and 1 for how confidently this was extracted
}

Use only what the document states. Never infer or invent. If a field has no
supporting content, return an empty list for it."""


@dataclass
class ExtractionResult:
    succeeded: bool
    model: str
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    extracted: dict[str, Any] | None = None
    confidence: float | None = None
    error: str | None = None
    attempts: int = field(default=1)

    @property
    def cost_usd(self) -> float:
        return (
            self.input_tokens / 1_000_000 * INPUT_USD_PER_MTOK
            + self.output_tokens / 1_000_000 * OUTPUT_USD_PER_MTOK
        )


class Extractor:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)

    async def extract(self, data: bytes, mime_type: str, filename: str) -> ExtractionResult:
        started = time.perf_counter()
        last_error = "unknown error"
        attempt = 1

        while attempt <= settings.gemini_max_retries:
            try:
                response = await asyncio.to_thread(self._call, data, mime_type, filename)
                parsed = self._parse(response.text)
                usage = response.usage_metadata

                return ExtractionResult(
                    succeeded=True,
                    model=settings.gemini_model,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                    output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                    extracted=parsed,
                    confidence=self._confidence(parsed),
                    attempts=attempt,
                )
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"
                if not self._is_retriable(error) or attempt == settings.gemini_max_retries:
                    break
                delay = min(2**attempt, 30) + random.uniform(0, 1)
                logger.warning(
                    "attempt %d/%d failed (%s), retrying in %.1fs",
                    attempt,
                    settings.gemini_max_retries,
                    last_error,
                    delay,
                )
                await asyncio.sleep(delay)
                attempt += 1

        return ExtractionResult(
            succeeded=False,
            model=settings.gemini_model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=last_error,
            attempts=attempt,
        )

    def _call(self, data: bytes, mime_type: str, filename: str):
        return self._client.models.generate_content(
            model=settings.gemini_model,
            contents=[
                types.Part.from_bytes(data=data, mime_type=mime_type),
                f"Extract structured data from this document (filename: {filename}).",
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.0,
                max_output_tokens=2048,
            ),
        )

    @staticmethod
    def _is_retriable(error: Exception) -> bool:
        text = str(error).lower()
        return any(
            marker in text
            for marker in ("429", "resource_exhausted", "503", "unavailable", "timeout", "500")
        )

    @staticmethod
    def _parse(raw: str | None) -> dict[str, Any]:
        if not raw:
            raise ValueError("Model returned an empty response")
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        return json.loads(cleaned)

    @staticmethod
    def _confidence(parsed: dict[str, Any]) -> float | None:
        value = parsed.get("confidence")
        if isinstance(value, (int, float)) and 0 <= value <= 1:
            return round(float(value), 3)
        return None

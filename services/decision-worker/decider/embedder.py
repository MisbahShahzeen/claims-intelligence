"""Embedding generation with a content-hash cache.

On a free-tier quota the cache is not an optimisation. Seeding a policy wording
produces dozens of clause embeddings; without the cache, re-running the seed
script burns the same quota again and eventually returns 429 partway through,
leaving the corpus half-populated.

Cache key is (content_hash, model). A different embedding model produces vectors
in a different space, so the model must be part of the key - otherwise switching
models would return stale vectors that are silently meaningless.
"""

import asyncio
import hashlib
import logging
import random
import time
from dataclasses import dataclass

from google import genai
from google.genai import types
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from decider.config import get_settings

logger = logging.getLogger("embedder")
settings = get_settings()

# Published rate for gemini-embedding-001, USD per million input tokens.
EMBEDDING_USD_PER_MTOK = 0.15

SELECT_CACHED = text("""
    SELECT content_hash, embedding
    FROM ai.embedding_cache
    WHERE model = :model AND content_hash = ANY(:hashes)
""")

INSERT_CACHED = text("""
    INSERT INTO ai.embedding_cache (content_hash, model, embedding)
    VALUES (:content_hash, :model, :embedding)
    ON CONFLICT (content_hash, model) DO NOTHING
""")

INSERT_USAGE = text("""
    INSERT INTO ai.ai_usage
        (claim_id, service, operation, model, input_tokens, output_tokens,
         cost_usd, latency_ms, cache_hit, succeeded)
    VALUES
        (:claim_id, 'decision-worker', 'embed', :model, :input_tokens, 0,
         :cost_usd, :latency_ms, :cache_hit, :succeeded)
""")


def content_hash(text_value: str) -> str:
    return hashlib.sha256(text_value.strip().encode("utf-8")).hexdigest()


@dataclass
class EmbeddingBatch:
    vectors: dict[str, list[float]]
    cache_hits: int
    api_calls: int
    input_tokens: int
    latency_ms: int

    @property
    def cost_usd(self) -> float:
        return self.input_tokens / 1_000_000 * EMBEDDING_USD_PER_MTOK


class Embedder:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)

    async def embed_texts(
        self, session: AsyncSession, texts: list[str], *, task_type: str
    ) -> EmbeddingBatch:
        """Embed a list of texts, returning {content_hash: vector}.

        task_type is RETRIEVAL_DOCUMENT when indexing a corpus, and
        RETRIEVAL_QUERY when embedding something to search with. Gemini produces
        different vectors for each, and mixing them degrades retrieval quality -
        a query embedded as a document does not sit where the search expects it.
        """
        started = time.perf_counter()
        unique: dict[str, str] = {}
        for value in texts:
            unique.setdefault(content_hash(value), value)

        vectors = await self._load_cached(session, list(unique))
        cache_hits = len(vectors)

        missing = [(h, unique[h]) for h in unique if h not in vectors]
        api_calls = 0
        input_tokens = 0

        for start in range(0, len(missing), settings.embedding_batch_size):
            chunk = missing[start : start + settings.embedding_batch_size]
            fresh, tokens = await self._call_with_retry(
                [value for _hash, value in chunk], task_type
            )
            api_calls += 1
            input_tokens += tokens

            for (digest, _value), vector in zip(chunk, fresh, strict=True):
                vectors[digest] = vector
                await session.execute(
                    INSERT_CACHED,
                    {
                        "content_hash": digest,
                        "model": settings.embedding_model,
                        "embedding": str(vector),
                    },
                )

        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "embedded %d text(s): %d cached, %d api call(s), %d tokens, %dms",
            len(unique),
            cache_hits,
            api_calls,
            input_tokens,
            latency_ms,
        )

        return EmbeddingBatch(
            vectors=vectors,
            cache_hits=cache_hits,
            api_calls=api_calls,
            input_tokens=input_tokens,
            latency_ms=latency_ms,
        )

    async def embed_query(self, session: AsyncSession, query: str) -> list[float]:
        batch = await self.embed_texts(session, [query], task_type="RETRIEVAL_QUERY")
        return batch.vectors[content_hash(query)]

    async def record_usage(
        self, session: AsyncSession, batch: EmbeddingBatch, claim_id: str | None = None
    ) -> None:
        await session.execute(
            INSERT_USAGE,
            {
                "claim_id": claim_id,
                "model": settings.embedding_model,
                "input_tokens": batch.input_tokens,
                "cost_usd": batch.cost_usd,
                "latency_ms": batch.latency_ms,
                "cache_hit": batch.api_calls == 0,
                "succeeded": True,
            },
        )

    async def _load_cached(
        self, session: AsyncSession, hashes: list[str]
    ) -> dict[str, list[float]]:
        if not hashes:
            return {}
        result = await session.execute(
            SELECT_CACHED, {"model": settings.embedding_model, "hashes": hashes}
        )
        return {row.content_hash: list(row.embedding) for row in result}

    async def _call_with_retry(
        self, texts: list[str], task_type: str
    ) -> tuple[list[list[float]], int]:
        last_error = "unknown error"
        for attempt in range(1, settings.max_retries + 1):
            try:
                response = await asyncio.to_thread(self._call, texts, task_type)
                vectors = [list(item.values) for item in response.embeddings]
                tokens = sum(len(t.split()) for t in texts) * 2
                return vectors, tokens
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"
                retriable = any(
                    marker in str(error).lower()
                    for marker in ("429", "resource_exhausted", "503", "unavailable", "timeout")
                )
                if not retriable or attempt == settings.max_retries:
                    break
                delay = min(2**attempt, 30) + random.uniform(0, 1)
                logger.warning(
                    "embedding attempt %d/%d failed (%s), retrying in %.1fs",
                    attempt,
                    settings.max_retries,
                    last_error,
                    delay,
                )
                await asyncio.sleep(delay)

        raise RuntimeError(f"Embedding failed after retries: {last_error}")

    def _call(self, texts: list[str], task_type: str):
        return self._client.models.embed_content(
            model=settings.embedding_model,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=settings.embedding_dimensions,
            ),
        )

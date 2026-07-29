"""IP-based throttling for unauthenticated endpoints.

Keyed on source address, not account. Locking an account after N failures lets
anyone who knows an email address deny that user service; throttling the source
stops credential stuffing without handing attackers a weapon.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# The whole window-rollover decision happens inside one statement, so two
# concurrent attempts cannot both read a stale count and both write 1.
CONSUME = text("""
    INSERT INTO claims.rate_limit_buckets (bucket_key, window_start, attempts)
    VALUES (:key, now(), 1)
    ON CONFLICT (bucket_key) DO UPDATE SET
        attempts = CASE
            WHEN claims.rate_limit_buckets.window_start
                 < now() - make_interval(secs => :window_seconds)
            THEN 1
            ELSE claims.rate_limit_buckets.attempts + 1
        END,
        window_start = CASE
            WHEN claims.rate_limit_buckets.window_start
                 < now() - make_interval(secs => :window_seconds)
            THEN now()
            ELSE claims.rate_limit_buckets.window_start
        END
    RETURNING attempts,
              EXTRACT(EPOCH FROM (
                  window_start + make_interval(secs => :window_seconds) - now()
              ))::int AS retry_after
""")

RESET = text("DELETE FROM claims.rate_limit_buckets WHERE bucket_key = :key")


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    attempts: int
    retry_after_seconds: int


async def consume(
    session: AsyncSession, key: str, *, limit: int, window_seconds: int
) -> RateLimitResult:
    row = (
        await session.execute(
            CONSUME, {"key": key[:128], "window_seconds": window_seconds}
        )
    ).one()
    await session.commit()

    return RateLimitResult(
        allowed=row.attempts <= limit,
        attempts=row.attempts,
        retry_after_seconds=max(row.retry_after, 1),
    )


async def reset(session: AsyncSession, key: str) -> None:
    """Clear the counter. Called on successful login so a legitimate user who
    mistyped their password a few times is not throttled afterwards."""
    await session.execute(RESET, {"key": key[:128]})
    await session.commit()

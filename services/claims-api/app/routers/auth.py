from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.deps import CurrentUser
from app.core.tokens import create_access_token
from app.schemas.user import LoginRequest, TokenResponse, UserRead
from app.services import rate_limit_service, user_service

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _client_key(request: Request) -> str:
    """Identify the caller for throttling.

    X-Forwarded-For is honoured because in Phase 12 this sits behind an ingress
    and request.client.host would be the proxy for every caller, collapsing all
    traffic into one bucket. The header is spoofable, so this is only safe when
    a trusted proxy overwrites it - which is exactly the deployment shape here.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return f"login:{forwarded.split(',')[0].strip()}"
    return f"login:{request.client.host if request.client else 'unknown'}"


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenResponse:
    key = _client_key(request)
    limit = await rate_limit_service.consume(
        session,
        key,
        limit=settings.login_rate_limit,
        window_seconds=settings.login_rate_window_seconds,
    )

    if not limit.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again shortly.",
            headers={"Retry-After": str(limit.retry_after_seconds)},
        )

    user = await user_service.authenticate(session, payload.email, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # Clear the counter on success so a legitimate user who mistyped a few
    # times is not throttled for the rest of the window.
    await rate_limit_service.reset(session, key)

    response.headers["X-RateLimit-Limit"] = str(settings.login_rate_limit)
    return TokenResponse(access_token=create_access_token(user.id, user.role))


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)

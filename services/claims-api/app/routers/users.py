from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import require_roles
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserRead
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])

AdminOnly = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    _: AdminOnly,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserRead:
    if await user_service.get_by_email(session, payload.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = await user_service.create_user(session, payload)
    return UserRead.model_validate(user)

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=72)
    role: UserRole
    authority_limit: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=2)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: str
    authority_limit: Decimal
    is_active: bool

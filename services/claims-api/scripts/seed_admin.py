import asyncio
import os
from decimal import Decimal

from app.core.db import SessionLocal
from app.schemas.user import UserCreate
from app.services import user_service
from app.models.user import UserRole


async def main() -> None:
    email = os.getenv("SEED_ADMIN_EMAIL", "admin@example.com")
    password = os.getenv("SEED_ADMIN_PASSWORD", "ChangeThisAdmin123!")

    async with SessionLocal() as session:
        if await user_service.get_by_email(session, email):
            print(f"Admin already exists: {email}")
            return
        await user_service.create_user(
            session,
            UserCreate(
                email=email,
                full_name="Platform Admin",
                password=password,
                role=UserRole.ADMIN,
                authority_limit=Decimal("0"),
            ),
        )
        print(f"Created admin: {email}")


if __name__ == "__main__":
    asyncio.run(main())

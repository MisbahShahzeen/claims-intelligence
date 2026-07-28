import asyncio
import os
from decimal import Decimal

from app.core.db import SessionLocal
from app.schemas.user import UserCreate
from app.services import user_service
from app.models.user import UserRole


async def main() -> None:
    email = os.getenv("SEED_ADMIN_EMAIL", "admin@example.com")
    password = os.getenv("SEED_ADMIN_PASSWORD")
    if not password:
        raise SystemExit(
            "SEED_ADMIN_PASSWORD is required. Run:\n"
            '  SEED_ADMIN_PASSWORD="your-password" python scripts/seed_admin.py'
        )

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

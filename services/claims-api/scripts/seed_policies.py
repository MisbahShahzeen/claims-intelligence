import asyncio
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.policy import Policy

POLICIES = [
    {
        "policy_number": "MOT-2026-0001",
        "policyholder_name": "Ananya Rao",
        "product_type": "motor",
        "effective_from": date(2026, 1, 1),
        "effective_to": date(2026, 12, 31),
        "coverage_limit": Decimal("800000.00"),
        "deductible": Decimal("5000.00"),
    },
    {
        "policy_number": "PRP-2026-0002",
        "policyholder_name": "Vikram Shetty",
        "product_type": "property",
        "effective_from": date(2026, 4, 1),
        "effective_to": date(2027, 3, 31),
        "coverage_limit": Decimal("2500000.00"),
        "deductible": Decimal("25000.00"),
    },
]


async def main() -> None:
    async with SessionLocal() as session:
        for data in POLICIES:
            exists = await session.scalar(
                select(Policy).where(Policy.policy_number == data["policy_number"])
            )
            if exists:
                print(f"exists: {data['policy_number']}")
                continue
            session.add(Policy(**data))
            print(f"created: {data['policy_number']}")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())

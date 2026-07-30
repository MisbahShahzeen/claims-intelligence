import asyncio
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from alembic import command
from app.core.config import get_settings
from app.core.db import get_session
from app.main import app
from app.models.user import User, UserRole
from app.schemas.user import UserCreate
from app.services import user_service

TEST_DB_NAME = "claims_test"
INIT_SQL = Path(__file__).resolve().parents[3] / "infra" / "postgres" / "init" / "01-extensions.sql"


def _swap_database(url: str, name: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/{name}"


settings = get_settings()
TEST_DATABASE_URL = _swap_database(settings.database_url, TEST_DB_NAME)
MAINTENANCE_URL = _swap_database(settings.database_url, "postgres")


async def _bootstrap() -> None:
    admin_engine = create_async_engine(MAINTENANCE_URL, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    await admin_engine.dispose()

    statements = [s.strip() for s in INIT_SQL.read_text().split(";") if s.strip()]
    test_engine = create_async_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    async with test_engine.connect() as conn:
        for statement in statements:
            await conn.execute(text(statement))
    await test_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(_bootstrap())

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        db = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield db
        finally:
            await db.close()
            await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncClient:
    async def override() -> AsyncSession:
        yield session

    app.dependency_overrides[get_session] = override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client
    app.dependency_overrides.clear()


async def _make_user(
    session: AsyncSession,
    email: str,
    role: UserRole,
    password: str,
    limit: str = "0",
) -> User:
    return await user_service.create_user(
        session,
        UserCreate(
            email=email,
            full_name=f"Test {role.value}",
            password=password,
            role=role,
            authority_limit=Decimal(limit),
        ),
    )


@pytest_asyncio.fixture
async def admin(session: AsyncSession) -> User:
    return await _make_user(session, "admin@example.com", UserRole.ADMIN, "AdminPass12345!")


@pytest_asyncio.fixture
async def adjuster(session: AsyncSession) -> User:
    return await _make_user(
        session, "adjuster@example.com", UserRole.ADJUSTER, "AdjusterPass123!", "50000.00"
    )


@pytest_asyncio.fixture
async def senior(session: AsyncSession) -> User:
    return await _make_user(
        session, "senior@example.com", UserRole.SENIOR_ADJUSTER, "SeniorPass12345!", "500000.00"
    )


@pytest.fixture
def auth_header():
    from app.core.tokens import create_access_token

    def _header(user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}

    return _header

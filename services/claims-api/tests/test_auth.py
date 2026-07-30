from app.models.user import User
from httpx import AsyncClient


async def test_login_returns_token(client: AsyncClient, adjuster: User):
    response = await client.post(
        "/auth/login",
        json={"email": "adjuster@example.com", "password": "AdjusterPass123!"},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


async def test_login_rejects_wrong_password(client: AsyncClient, adjuster: User):
    response = await client.post(
        "/auth/login",
        json={"email": "adjuster@example.com", "password": "NotThePassword1!"},
    )

    assert response.status_code == 401


async def test_login_on_unknown_email_matches_wrong_password(client: AsyncClient):
    response = await client.post(
        "/auth/login",
        json={"email": "ghost@example.com", "password": "NotThePassword1!"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


async def test_me_requires_token(client: AsyncClient):
    assert (await client.get("/auth/me")).status_code == 401


async def test_me_returns_current_user(client: AsyncClient, adjuster: User, auth_header):
    response = await client.get("/auth/me", headers=auth_header(adjuster))

    assert response.status_code == 200
    assert response.json()["email"] == "adjuster@example.com"
    assert response.json()["authority_limit"] == "50000.00"


async def test_inactive_user_is_rejected(client: AsyncClient, session, adjuster: User, auth_header):
    adjuster.is_active = False
    await session.commit()

    assert (await client.get("/auth/me", headers=auth_header(adjuster))).status_code == 401

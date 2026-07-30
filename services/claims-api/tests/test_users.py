from app.models.user import User
from httpx import AsyncClient


async def test_admin_can_create_user(client: AsyncClient, admin: User, auth_header):
    response = await client.post(
        "/users",
        headers=auth_header(admin),
        json={
            "email": "new.adjuster@example.com",
            "full_name": "New Adjuster",
            "password": "BrandNewPass12!",
            "role": "adjuster",
            "authority_limit": "25000.00",
        },
    )

    assert response.status_code == 201
    assert response.json()["role"] == "adjuster"


async def test_adjuster_cannot_create_user(client: AsyncClient, adjuster: User, auth_header):
    response = await client.post(
        "/users",
        headers=auth_header(adjuster),
        json={
            "email": "sneaky@example.com",
            "full_name": "Sneaky",
            "password": "SneakyPass123!",
            "role": "admin",
        },
    )

    assert response.status_code == 403


async def test_duplicate_email_is_rejected(client: AsyncClient, admin: User, auth_header):
    payload = {
        "email": "dupe@example.com",
        "full_name": "Dupe",
        "password": "DupePass12345!",
        "role": "adjuster",
    }

    assert (
        await client.post("/users", headers=auth_header(admin), json=payload)
    ).status_code == 201
    assert (
        await client.post("/users", headers=auth_header(admin), json=payload)
    ).status_code == 409


async def test_short_password_is_rejected(client: AsyncClient, admin: User, auth_header):
    response = await client.post(
        "/users",
        headers=auth_header(admin),
        json={
            "email": "weak@example.com",
            "full_name": "Weak",
            "password": "short",
            "role": "adjuster",
        },
    )

    assert response.status_code == 422

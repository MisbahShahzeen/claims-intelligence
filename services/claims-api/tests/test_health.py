from app.main import app
from httpx import ASGITransport, AsyncClient


async def test_live_returns_alive():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"

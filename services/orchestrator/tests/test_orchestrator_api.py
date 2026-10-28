"""Pruebas unitarias de los endpoints de la API de administración del orquestador."""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from services.orchestrator.src.main import app, engine
from services.orchestrator.src.models import StateEnum


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Cliente HTTP asíncrono para pruebas de la API del orquestador."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testorchestrator") as ac:
        yield ac


@pytest.mark.asyncio
async def test_api_health(client: AsyncClient) -> None:
    """Verifica que /health responda 200 OK."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_api_status(client: AsyncClient) -> None:
    """Verifica que /status retorne el estado actual de la FSM y parámetros."""
    engine.state_machine._state = StateEnum.HEALTHY
    engine.active_cloud = "cloud_a"

    response = await client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert data["current_state"] == "HEALTHY"
    assert data["active_cloud"] == "cloud_a"
    assert data["failure_threshold"] == 3


@pytest.mark.asyncio
async def test_api_reset(client: AsyncClient) -> None:
    """Verifica que POST /reset reinicie la FSM a HEALTHY."""
    engine.state_machine._state = StateEnum.FAILED_OVER
    engine.active_cloud = "cloud_b"

    response = await client.post("/reset")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "reset"
    assert data["to_state"] == "HEALTHY"

    # Verificar estado en /status
    status_resp = await client.get("/status")
    assert status_resp.json()["current_state"] == "HEALTHY"
    assert status_resp.json()["active_cloud"] == "cloud_a"


@pytest.mark.asyncio
async def test_api_events(client: AsyncClient) -> None:
    """Verifica que /events devuelva la lista histórica de eventos."""
    response = await client.get("/events")
    assert response.status_code == 200
    events = response.json()
    assert isinstance(events, list)


@pytest.mark.asyncio
async def test_api_metrics(client: AsyncClient) -> None:
    """Verifica que /metrics exponga métricas en formato Prometheus."""
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "orchestrator_state_code" in response.text

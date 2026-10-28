"""Pruebas unitarias y de contrato de la aplicación de referencia."""

import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from services.reference_app.src.database import DatabaseManager, OrderModel, db_manager
from services.reference_app.src.main import app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Cliente HTTP asíncrono para pruebas de FastAPI."""
    app.dependency_overrides.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_check_healthy(client: AsyncClient) -> None:
    """Verifica que /health responda 200 y status 'healthy' si la BD responde."""
    with patch.object(db_manager, "check_health", new_callable=AsyncMock) as mock_health:
        mock_health.return_value = (True, "primary", 1.25)
        response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["db_ok"] is True
        assert data["db_role"] == "primary"
        assert data["db_latency_ms"] == 1.25


@pytest.mark.asyncio
async def test_health_check_unhealthy(client: AsyncClient) -> None:
    """Verifica que /health responda 503 si la base de datos no está disponible."""
    with patch.object(db_manager, "check_health", new_callable=AsyncMock) as mock_health:
        mock_health.return_value = (False, "unknown", 1000.0)
        response = await client.get("/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["db_ok"] is False
        assert data["db_role"] == "unknown"


@pytest.mark.asyncio
async def test_metrics_endpoint(client: AsyncClient) -> None:
    """Verifica que /metrics exponga métricas en formato Prometheus."""
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text or "orders_total" in response.text


@pytest.mark.asyncio
async def test_create_order_rejected_on_replica(client: AsyncClient) -> None:
    """Verifica que las escrituras en modo réplica sean rechazadas con HTTP 503."""
    with patch.object(db_manager, "check_role", new_callable=AsyncMock) as mock_role:
        mock_role.return_value = "replica"
        payload = {
            "order_id": str(uuid4()),
            "customer_id": 101,
            "amount": "150.50",
        }
        response = await client.post("/orders", json=payload)
        assert response.status_code == 503
        assert "réplica" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_order_success(client: AsyncClient) -> None:
    """Verifica que un pedido nuevo responda 201 Created tras commit exitoso."""
    mock_session = AsyncMock()
    mock_session.get.return_value = None  # No existe previamente
    mock_session.add = MagicMock()

    async def _mock_refresh(instance: OrderModel) -> None:
        instance.seq = 1
        instance.committed_at = datetime.now(UTC)

    mock_session.refresh.side_effect = _mock_refresh
    mock_session.commit = AsyncMock()

    async def _override_session() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[db_manager.get_session] = _override_session

    with patch.object(db_manager, "check_role", new_callable=AsyncMock, return_value="primary"):
        test_id = uuid4()
        payload = {
            "order_id": str(test_id),
            "customer_id": 202,
            "amount": "99.99",
        }
        response = await client.post("/orders", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["order_id"] == str(test_id)
        assert data["customer_id"] == 202
        assert float(data["amount"]) == 99.99


@pytest.mark.asyncio
async def test_create_order_idempotent(client: AsyncClient) -> None:
    """Verifica que si el order_id ya existe, responda 200 OK sin duplicar."""
    existing_id = uuid4()
    existing_order = OrderModel(
        order_id=existing_id,
        customer_id=303,
        amount=Decimal("45.00"),
        status="COMPLETED",
        seq=5,
        committed_at=datetime.now(UTC),
    )
    mock_session = AsyncMock()
    mock_session.get.return_value = existing_order

    async def _override_session() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[db_manager.get_session] = _override_session

    with patch.object(db_manager, "check_role", new_callable=AsyncMock, return_value="primary"):
        payload = {
            "order_id": str(existing_id),
            "customer_id": 303,
            "amount": "45.00",
        }
        response = await client.post("/orders", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["order_id"] == str(existing_id)
        assert data["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_get_order_success(client: AsyncClient) -> None:
    """Verifica la consulta exitosa de un pedido existente por UUID."""
    order_id = uuid4()
    order = OrderModel(
        order_id=order_id,
        customer_id=404,
        amount=Decimal("120.00"),
        status="COMPLETED",
        seq=10,
        committed_at=datetime.now(UTC),
    )
    mock_session = AsyncMock()
    mock_session.get.return_value = order

    async def _override_session() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[db_manager.get_session] = _override_session

    response = await client.get(f"/orders/{order_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["order_id"] == str(order_id)
    assert data["customer_id"] == 404


@pytest.mark.asyncio
async def test_get_order_not_found(client: AsyncClient) -> None:
    """Verifica que un pedido inexistente devuelva 404 Not Found."""
    mock_session = AsyncMock()
    mock_session.get.return_value = None

    async def _override_session() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[db_manager.get_session] = _override_session

    response = await client.get(f"/orders/{uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_orders(client: AsyncClient) -> None:
    """Verifica el listado de pedidos con y sin filtro de cliente."""
    mock_orders = [
        OrderModel(
            order_id=uuid4(),
            customer_id=505,
            amount=Decimal("10.00"),
            status="COMPLETED",
            seq=i,
            committed_at=datetime.now(UTC),
        )
        for i in range(1, 4)
    ]
    mock_session = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = mock_orders
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute.return_value = mock_result

    async def _override_session() -> AsyncGenerator[Any, None]:
        yield mock_session

    app.dependency_overrides[db_manager.get_session] = _override_session

    response = await client.get("/orders?customer_id=505&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    assert data[0]["customer_id"] == 505


@pytest.mark.asyncio
async def test_role_cache_ttl() -> None:
    """Verifica que la detección de rol respete la caché y se actualice tras el TTL."""
    mgr = DatabaseManager("postgresql+asyncpg://mock/db")
    mgr._cached_role = "primary"
    mgr._last_role_check = time.monotonic()

    # Primera consulta dentro del TTL -> usa caché
    role = await mgr.check_role(force_refresh=False)
    assert role == "primary"

    # Simular paso del tiempo mayor al TTL
    mgr._last_role_check = time.monotonic() - 5.0

    mock_conn = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar.return_value = True  # en recuperación
    mock_conn.execute.return_value = mock_result

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=None)
    mgr._engine = mock_engine

    new_role = await mgr.check_role(force_refresh=False)
    assert new_role == "replica"


@pytest.mark.asyncio
async def test_database_manager_check_health() -> None:
    """Verifica la ejecución de check_health en DatabaseManager."""
    mgr = DatabaseManager("postgresql+asyncpg://mock/db")

    mock_conn = AsyncMock()
    mock_result = MagicMock()
    mock_result.first.return_value = (1, False)  # 1, not in recovery -> primary
    mock_conn.execute.return_value = mock_result

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=None)
    mgr._engine = mock_engine

    ok, role, latency = await mgr.check_health()
    assert ok is True
    assert role == "primary"
    assert latency >= 0.0

    # Simular fallo en la conexión
    mock_engine.connect.return_value.__aenter__ = AsyncMock(side_effect=Exception("DB down"))
    ok_fail, role_fail, latency_fail = await mgr.check_health()
    assert ok_fail is False
    assert role_fail == "unknown"

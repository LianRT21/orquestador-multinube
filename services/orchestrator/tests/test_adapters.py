"""Pruebas unitarias de adaptadores de PostgreSQL, HTTP Prober y Clock."""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.orchestrator.src.adapters.postgres import AsyncpgPostgresPromoter
from services.orchestrator.src.adapters.probe import HttpxProbeClient
from services.orchestrator.src.clock import MockClock, SystemClock
from services.orchestrator.src.main import persist_event_jsonl, probe_background_worker
from services.orchestrator.src.models import OrchestratorEvent, ProbeStatus, StateEnum


@pytest.mark.asyncio
async def test_system_clock() -> None:
    """Verifica el funcionamiento del reloj del sistema."""
    clock = SystemClock()
    assert clock.now_ns() > 0
    assert clock.now_s() > 0
    await clock.sleep(0.001)


@pytest.mark.asyncio
async def test_mock_clock() -> None:
    """Verifica el avance determinista del reloj simulado."""
    clock = MockClock(start_ns=1_000_000_000)
    assert clock.now_s() == 1.0
    await clock.sleep(2.5)
    assert clock.now_s() == 3.5


@pytest.mark.asyncio
async def test_postgres_promoter_success() -> None:
    """Verifica la promoción exitosa de la réplica."""
    promoter = AsyncpgPostgresPromoter()
    mock_conn = AsyncMock()
    mock_conn.fetchval.return_value = True

    with patch("asyncpg.connect", return_value=mock_conn):
        duration = await promoter.promote_replica(
            host="db-b",
            port=5432,
            user="postgres",
            password="pwd",
            dbname="orders_db",
        )
        assert duration >= 0.0
        mock_conn.fetchval.assert_called_once()
        mock_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_postgres_promoter_set_read_only() -> None:
    """Verifica la colocación de la base de datos primaria en solo lectura (fencing)."""
    promoter = AsyncpgPostgresPromoter()
    mock_conn = AsyncMock()

    with patch("asyncpg.connect", return_value=mock_conn):
        ok = await promoter.set_read_only("db-a", 5432, "postgres", "pwd", "orders_db")
        assert ok is True
        mock_conn.execute.assert_any_call("ALTER SYSTEM SET default_transaction_read_only = 'on';")

    # Simular fallo de conexión (esperado si la primaria está apagada)
    with patch("asyncpg.connect", side_effect=Exception("Connection refused")):
        ok_fail = await promoter.set_read_only("db-a", 5432, "postgres", "pwd", "orders_db")
        assert ok_fail is False


@pytest.mark.asyncio
async def test_httpx_probe_client_ok() -> None:
    """Verifica sonda exitosa HTTP 200 con db_ok=True."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"db_ok": True, "db_role": "primary"}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    probe = HttpxProbeClient(client=mock_client)
    res = await probe.probe_endpoint("http://app-a:8000/health", timeout_s=1.0)

    assert res.is_healthy is True
    assert res.status == ProbeStatus.OK
    assert res.db_role == "primary"
    await probe.close()


@pytest.mark.asyncio
async def test_httpx_probe_client_http_error() -> None:
    """Verifica detección de error HTTP 500."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    probe = HttpxProbeClient(client=mock_client)
    res = await probe.probe_endpoint("http://app-a:8000/health", timeout_s=1.0)

    assert res.is_healthy is False
    assert res.status == ProbeStatus.HTTP_ERROR
    assert res.status_code == 500


@pytest.mark.asyncio
async def test_httpx_probe_client_degraded_latency() -> None:
    """Verifica detección de degradación parcial por alta latencia (F4)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"db_ok": True, "db_role": "primary"}

    mock_client = AsyncMock()

    async def _slow_get(*args: object, **kwargs: object) -> MagicMock:
        await asyncio.sleep(0.05)  # 50 ms
        return mock_resp

    mock_client.get.side_effect = _slow_get

    probe = HttpxProbeClient(client=mock_client)
    # Umbral de 10 ms para que 50 ms active degradación
    res = await probe.probe_endpoint(
        "http://app-a:8000/health", timeout_s=1.0, degraded_latency_ms=10.0
    )

    assert res.status == ProbeStatus.DEGRADED_LATENCY
    assert not res.is_healthy


@pytest.mark.asyncio
async def test_httpx_probe_client_timeout() -> None:
    """Verifica captura de timeout en sonda."""
    mock_client = AsyncMock()
    mock_client.get.side_effect = httpx.TimeoutException("Connection timed out")

    probe = HttpxProbeClient(client=mock_client)
    res = await probe.probe_endpoint("http://app-a:8000/health", timeout_s=1.0)

    assert res.status == ProbeStatus.TIMEOUT
    assert not res.is_healthy


@pytest.mark.asyncio
async def test_httpx_probe_client_db_unhealthy() -> None:
    """Verifica detección de db_ok=False en JSON de respuesta."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"db_ok": False, "db_role": "unknown"}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    probe = HttpxProbeClient(client=mock_client)
    res = await probe.probe_endpoint("http://app-a:8000/health", timeout_s=1.0)

    assert res.status == ProbeStatus.DB_UNHEALTHY
    assert not res.is_healthy


@pytest.mark.asyncio
async def test_httpx_verify_order_flow() -> None:
    """Verifica flujo sintético de órdenes (POST + GET)."""
    mock_client = AsyncMock()

    # Caso 1: Flujo exitoso
    post_ok = MagicMock(status_code=201)
    get_ok = MagicMock(status_code=200)
    mock_client.post.return_value = post_ok
    mock_client.get.return_value = get_ok

    probe = HttpxProbeClient(client=mock_client)
    ok = await probe.verify_order_flow("http://proxy:80/orders")
    assert ok is True

    # Caso 2: Fallo en POST
    mock_client.post.return_value = MagicMock(status_code=503, text="Service Unavailable")
    fail_post = await probe.verify_order_flow("http://proxy:80/orders")
    assert fail_post is False

    # Caso 3: Fallo en GET
    mock_client.post.return_value = MagicMock(status_code=201)
    mock_client.get.return_value = MagicMock(status_code=404)
    fail_get = await probe.verify_order_flow("http://proxy:80/orders")
    assert fail_get is False


@pytest.mark.asyncio
async def test_persist_event_and_background_worker(tmp_path: object) -> None:
    """Verifica persistencia en JSONL y ciclo del worker en segundo plano."""
    from pathlib import Path

    test_file = str(Path(str(tmp_path)) / "events.jsonl")
    ev = OrchestratorEvent(
        name="test_event",
        from_state=StateEnum.HEALTHY,
        to_state=StateEnum.SUSPECT,
        timestamp_ns=1_000_000,
        details={"info": "unit_test"},
    )
    persist_event_jsonl(ev, test_file)

    with open(test_file, encoding="utf-8") as f:
        content = f.read()
        assert "test_event" in content
        assert "unit_test" in content

    # Probar cancelación del worker en segundo plano
    mock_engine = MagicMock()
    mock_engine.run_probe_cycle = AsyncMock(return_value=[])
    mock_engine.state_machine.current_state = StateEnum.HEALTHY
    mock_engine.state_machine.consecutive_failures = 0
    mock_engine.last_rto_seconds = None
    mock_engine.settings.PROBE_INTERVAL_S = 0.001

    worker = asyncio.create_task(probe_background_worker(mock_engine))
    await asyncio.sleep(0.01)
    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker
    assert mock_engine.run_probe_cycle.call_count >= 1

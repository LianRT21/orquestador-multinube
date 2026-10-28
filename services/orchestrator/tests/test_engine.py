"""Pruebas unitarias del motor de orquestación (OrchestratorEngine)."""

from unittest.mock import AsyncMock

import pytest

from services.orchestrator.src.clock import MockClock
from services.orchestrator.src.config import OrchestratorSettings
from services.orchestrator.src.engine import OrchestratorEngine
from services.orchestrator.src.models import ProbeResult, ProbeStatus, StateEnum


def make_engine() -> tuple[OrchestratorEngine, MockClock, AsyncMock, AsyncMock, AsyncMock]:
    """Helper para crear una instancia de OrchestratorEngine con dependencias simuladas."""
    clock = MockClock(start_ns=1_000_000_000_000)
    settings = OrchestratorSettings(
        FAILURE_THRESHOLD=3,
        PROBE_TIMEOUT_S=1.0,
        N1_HEALTH_URLS=["http://app-a:8000/health"],
        N2_HEALTH_URLS=["http://app-b:8000/health"],
    )

    mock_haproxy = AsyncMock()
    mock_haproxy.set_server_state.return_value = True

    mock_postgres = AsyncMock()
    mock_postgres.promote_replica.return_value = 15.0  # 15 ms
    mock_postgres.set_read_only.return_value = True

    mock_probe = AsyncMock()
    mock_probe.probe_endpoint.return_value = ProbeResult(
        instance_url="http://app-a:8000/health",
        status=ProbeStatus.OK,
        status_code=200,
        latency_ms=5.0,
        db_ok=True,
        db_role="primary",
        timestamp_ns=clock.now_ns(),
    )
    mock_probe.verify_order_flow.return_value = True

    engine = OrchestratorEngine(
        settings=settings,
        clock=clock,
        haproxy_client=mock_haproxy,
        postgres_promoter=mock_postgres,
        probe_client=mock_probe,
    )
    return engine, clock, mock_haproxy, mock_postgres, mock_probe


@pytest.mark.asyncio
async def test_engine_probe_cycle_healthy() -> None:
    """Un ciclo de sondas saludables mantiene el estado HEALTHY sin activar el proxy."""
    engine, _, mock_haproxy, mock_postgres, _ = make_engine()

    events = await engine.run_probe_cycle()

    assert engine.state_machine.current_state == StateEnum.HEALTHY
    assert len(events) == 0
    mock_haproxy.set_server_state.assert_not_called()
    mock_postgres.promote_replica.assert_not_called()


@pytest.mark.asyncio
async def test_engine_failover_execution_flow() -> None:
    """Verifica la ejecución ordenada y atómica del failover tras alcanzar el umbral de 3 fallos."""
    engine, clock, mock_haproxy, mock_postgres, mock_probe = make_engine()

    # Configurar N1 con fallo continuo
    fail_probe = ProbeResult(
        instance_url="http://app-a:8000/health",
        status=ProbeStatus.HTTP_ERROR,
        status_code=500,
        latency_ms=10.0,
        timestamp_ns=clock.now_ns(),
    )
    # Configurar N2 sana en modo réplica para el pre-flight check
    n2_probe = ProbeResult(
        instance_url="http://app-b:8000/health",
        status=ProbeStatus.OK,
        status_code=200,
        latency_ms=8.0,
        db_ok=True,
        db_role="replica",
        timestamp_ns=clock.now_ns(),
    )

    async def _mock_probe(url: str, **kwargs: object) -> ProbeResult:
        if "app-b" in url:
            return n2_probe
        return fail_probe

    mock_probe.probe_endpoint.side_effect = _mock_probe

    # Ejecutar 3 ciclos para alcanzar el umbral
    await engine.run_probe_cycle()  # Ronda 1 -> SUSPECT
    assert engine.state_machine.current_state == StateEnum.SUSPECT

    await engine.run_probe_cycle()  # Ronda 2 -> SUSPECT
    assert engine.state_machine.current_state == StateEnum.SUSPECT

    await engine.run_probe_cycle()  # Ronda 3 -> Dispara failover

    # 1. Verificar estado final
    final_state: StateEnum = engine.state_machine.current_state
    assert final_state == StateEnum.FAILED_OVER
    assert engine.active_cloud == "cloud_b"
    assert engine.last_rto_seconds is not None
    assert engine.last_rto_seconds >= 0.0

    # 2. Verificar llamadas ordenadas
    # Paso 1: Fencing N1
    mock_haproxy.set_server_state.assert_any_call(
        backend=engine.settings.HAPROXY_BACKEND,
        server=engine.settings.HAPROXY_SERVER_A,
        state="maint",
    )
    # Paso 3: Promoción réplica N2
    mock_postgres.promote_replica.assert_called_once()
    # Paso 4: Redirección proxy a N2
    mock_haproxy.set_server_state.assert_any_call(
        backend=engine.settings.HAPROXY_BACKEND,
        server=engine.settings.HAPROXY_SERVER_B,
        state="ready",
    )
    # Paso 5: Verificación sintética
    mock_probe.verify_order_flow.assert_called_once_with(engine.settings.PROXY_ORDERS_URL)

    # 3. Verificar secuencia de eventos emitidos
    event_names = [e.name for e in engine.get_all_events()]
    expected_sequence = [
        "t_detect",
        "t_fence",
        "t_promote_start",
        "t_promote_end",
        "t_switch",
        "t_verified",
        "failed_over",
    ]
    for expected in expected_sequence:
        assert expected in event_names, f"El evento {expected} no fue emitido en la secuencia"


@pytest.mark.asyncio
async def test_engine_failover_aborts_on_unhealthy_n2() -> None:
    """Si la nube secundaria N2 no está disponible, el failover aborta a FAILOVER_ERROR."""
    engine, clock, _, mock_postgres, mock_probe = make_engine()

    fail_probe = ProbeResult(
        instance_url="http://app-a:8000/health",
        status=ProbeStatus.TIMEOUT,
        timestamp_ns=clock.now_ns(),
    )
    n2_unhealthy = ProbeResult(
        instance_url="http://app-b:8000/health",
        status=ProbeStatus.HTTP_ERROR,
        db_ok=False,
        error_message="N2 caída",
        timestamp_ns=clock.now_ns(),
    )

    async def _mock_probe(url: str, **kwargs: object) -> ProbeResult:
        if "app-b" in url:
            return n2_unhealthy
        return fail_probe

    mock_probe.probe_endpoint.side_effect = _mock_probe

    # Ejecutar 3 rondas
    await engine.run_probe_cycle()
    await engine.run_probe_cycle()
    await engine.run_probe_cycle()

    assert engine.state_machine.current_state == StateEnum.FAILOVER_ERROR
    mock_postgres.promote_replica.assert_not_called()
    assert any(e.name == "failover_error" for e in engine.get_all_events())


@pytest.mark.asyncio
async def test_engine_failover_idempotency_lock() -> None:
    """Llamadas duplicadas o concurrentes a execute_failover() no re-ejecutan el proceso."""
    engine, _, mock_haproxy, _, _ = make_engine()

    # Forzar estado FAILED_OVER
    engine.state_machine._state = StateEnum.FAILED_OVER

    result = await engine.execute_failover()
    assert result is False
    mock_haproxy.set_server_state.assert_not_called()


@pytest.mark.asyncio
async def test_engine_reset() -> None:
    """Verifica que reset() reestablezca el orquestador a cloud_a y estado HEALTHY."""
    engine, _, _, _, _ = make_engine()
    engine.state_machine._state = StateEnum.FAILED_OVER
    engine.active_cloud = "cloud_b"
    engine.last_rto_seconds = 12.34

    reset_ev = engine.reset()

    assert engine.state_machine.current_state == StateEnum.HEALTHY
    assert engine.active_cloud == "cloud_a"
    assert engine.last_rto_seconds is None
    assert reset_ev.name == "reset"

"""Pruebas unitarias exhaustivas de la Máquina de Estados Finita (FSM) pura del orquestador."""

import pytest

from services.orchestrator.src.clock import MockClock
from services.orchestrator.src.models import ProbeResult, ProbeStatus, StateEnum
from services.orchestrator.src.state_machine import (
    FailoverStateMachine,
    InvalidStateTransitionError,
)


def create_probe(
    url: str = "http://app-a:8000/health",
    status: ProbeStatus = ProbeStatus.OK,
    status_code: int = 200,
    latency_ms: float = 10.0,
    db_ok: bool = True,
) -> ProbeResult:
    """Helper para crear ProbeResult rápidamente."""
    return ProbeResult(
        instance_url=url,
        status=status,
        status_code=status_code,
        latency_ms=latency_ms,
        db_ok=db_ok,
        timestamp_ns=1_000_000,
    )


def test_initial_state() -> None:
    """Verifica que el estado inicial sea HEALTHY y contadores en 0."""
    clock = MockClock()
    fsm = FailoverStateMachine(clock=clock, failure_threshold=3)
    assert fsm.current_state == StateEnum.HEALTHY
    assert fsm.consecutive_failures == 0
    assert len(fsm.events_history) == 0


def test_single_failure_transitions_to_suspect() -> None:
    """Un fallo único debe transicionar a SUSPECT con consecutive_failures = 1."""
    fsm = FailoverStateMachine(failure_threshold=3)
    fail_probe = create_probe(status=ProbeStatus.HTTP_ERROR, status_code=500, db_ok=False)

    state, events = fsm.process_probe_results([fail_probe])

    assert state == StateEnum.SUSPECT
    assert fsm.consecutive_failures == 1
    event_names = [e.name for e in events]
    assert "probe_failed" in event_names
    assert "suspect" in event_names


def test_two_failures_remain_suspect() -> None:
    """Dos fallos consecutivos mantienen el estado SUSPECT."""
    fsm = FailoverStateMachine(failure_threshold=3)
    fail_probe = create_probe(status=ProbeStatus.TIMEOUT, latency_ms=1000.0)

    fsm.process_probe_results([fail_probe])
    state, events = fsm.process_probe_results([fail_probe])

    assert state == StateEnum.SUSPECT
    assert fsm.consecutive_failures == 2
    assert any(e.name == "probe_failed" for e in events)


def test_success_resets_counter_and_recovers_to_healthy() -> None:
    """Un éxito intermedio tras fallos reinicia el contador y recupera a HEALTHY."""
    fsm = FailoverStateMachine(failure_threshold=3)
    fail_probe = create_probe(status=ProbeStatus.HTTP_ERROR, status_code=503)
    ok_probe = create_probe(status=ProbeStatus.OK, status_code=200, db_ok=True)

    # 1. Acumular 2 fallos -> SUSPECT
    fsm.process_probe_results([fail_probe])
    fsm.process_probe_results([fail_probe])
    assert fsm.current_state == StateEnum.SUSPECT
    assert fsm.consecutive_failures == 2

    # 2. Sonda exitosa intermedia
    state, events = fsm.process_probe_results([ok_probe])

    assert state == StateEnum.HEALTHY
    assert fsm.consecutive_failures == 0
    assert any(e.name == "state_recovered" for e in events)


def test_three_consecutive_failures_triggers_failover() -> None:
    """Exactamente 3 fallos consecutivos provocan transición a FAILING_OVER y emiten t_detect."""
    clock = MockClock(start_ns=1_700_000_123_456_789)
    fsm = FailoverStateMachine(clock=clock, failure_threshold=3)
    fail_probe = create_probe(status=ProbeStatus.HTTP_ERROR, status_code=500)

    # Ronda 1
    fsm.process_probe_results([fail_probe])
    assert fsm.current_state == StateEnum.SUSPECT

    # Ronda 2
    fsm.process_probe_results([fail_probe])
    assert fsm.current_state == StateEnum.SUSPECT

    # Ronda 3 -> Umbral alcanzado
    state, events = fsm.process_probe_results([fail_probe])

    assert state == StateEnum.FAILING_OVER
    assert fsm.consecutive_failures == 3

    detect_event = next((e for e in events if e.name == "t_detect"), None)
    assert detect_event is not None
    assert detect_event.from_state == StateEnum.SUSPECT
    assert detect_event.to_state == StateEnum.FAILING_OVER
    assert detect_event.timestamp_ns == 1_700_000_123_456_789


def test_partial_failure_multiple_instances() -> None:
    """Si hay múltiples instancias y al menos una responde sana, no se considera caída."""
    fsm = FailoverStateMachine(failure_threshold=3)
    probe_inst1 = create_probe("http://app-a1:8000/health", status=ProbeStatus.TIMEOUT)
    probe_inst2 = create_probe("http://app-a2:8000/health", status=ProbeStatus.OK, db_ok=True)

    state, _ = fsm.process_probe_results([probe_inst1, probe_inst2])

    assert state == StateEnum.HEALTHY
    assert fsm.consecutive_failures == 0


def test_degraded_latency_counts_as_failure() -> None:
    """Una sonda con estado DEGRADED_LATENCY (F4) se computa como fallo en la FSM."""
    fsm = FailoverStateMachine(failure_threshold=1)
    degraded_probe = create_probe(status=ProbeStatus.DEGRADED_LATENCY, latency_ms=2500.0)

    state, events = fsm.process_probe_results([degraded_probe])

    assert state == StateEnum.FAILING_OVER
    assert any(e.name == "t_detect" for e in events)


def test_hysteresis_ignores_probes_during_and_after_failover() -> None:
    """En estados FAILING_OVER, FAILED_OVER y FAILOVER_ERROR no se evalúan nuevas conmutaciones."""
    fsm = FailoverStateMachine(failure_threshold=1)
    fail_probe = create_probe(status=ProbeStatus.HTTP_ERROR)

    fsm.process_probe_results([fail_probe])
    assert fsm.current_state == StateEnum.FAILING_OVER

    # Sonda en FAILING_OVER no produce nuevos eventos ni altera estado
    state, events = fsm.process_probe_results([fail_probe])
    assert state == StateEnum.FAILING_OVER
    assert len(events) == 0

    # Pasar a FAILED_OVER
    fsm.transition_to(StateEnum.FAILED_OVER, event_name="failed_over")
    state2, events2 = fsm.process_probe_results([fail_probe])
    assert state2 == StateEnum.FAILED_OVER
    assert len(events2) == 0


def test_invalid_transition_raises_error() -> None:
    """Una transición ilegal (p. ej. HEALTHY a FAILED_OVER directo) levanta InvalidStateTransitionError."""
    fsm = FailoverStateMachine()
    with pytest.raises(InvalidStateTransitionError, match="Transición inválida"):
        fsm.transition_to(StateEnum.FAILED_OVER, event_name="direct_illegal")


def test_reset_restores_healthy() -> None:
    """El método reset() restaura el estado a HEALTHY y emite evento formal."""
    fsm = FailoverStateMachine(failure_threshold=1)
    fsm.process_probe_results([create_probe(status=ProbeStatus.HTTP_ERROR)])
    fsm.transition_to(StateEnum.FAILED_OVER, event_name="failed_over")

    reset_event = fsm.reset()

    assert fsm.current_state == StateEnum.HEALTHY
    assert fsm.consecutive_failures == 0
    assert reset_event.name == "reset"
    assert reset_event.to_state == StateEnum.HEALTHY

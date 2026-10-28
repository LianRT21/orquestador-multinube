"""Máquina de Estados Finita (FSM) pura para conmutación por error.

Diseñada sin dependencias directas de E/S de red ni reloj físico del sistema,
permitiendo pruebas unitarias deterministas y cobertura matemática exhaustiva.
"""

from typing import Any

from services.orchestrator.src.clock import ClockProtocol, SystemClock
from services.orchestrator.src.models import OrchestratorEvent, ProbeResult, StateEnum


class InvalidStateTransitionError(Exception):
    """Excepción al intentar una transición no permitida por la máquina de estados."""

    pass


class FailoverStateMachine:
    """Máquina de estados determinista y auditable para el orquestador."""

    # Transiciones válidas del ciclo de resiliencia
    ALLOWED_TRANSITIONS: dict[StateEnum, set[StateEnum]] = {
        StateEnum.HEALTHY: {StateEnum.SUSPECT, StateEnum.FAILING_OVER},
        StateEnum.SUSPECT: {StateEnum.HEALTHY, StateEnum.FAILING_OVER},
        StateEnum.FAILING_OVER: {StateEnum.FAILED_OVER, StateEnum.FAILOVER_ERROR},
        StateEnum.FAILED_OVER: set(),  # Requiere reset explícito (histéresis ADR-0002)
        StateEnum.FAILOVER_ERROR: set(),  # Requiere reset explícito
    }

    def __init__(
        self,
        clock: ClockProtocol | None = None,
        failure_threshold: int = 3,
    ) -> None:
        self.clock: ClockProtocol = clock or SystemClock()
        self.failure_threshold = failure_threshold
        self._state: StateEnum = StateEnum.HEALTHY
        self._consecutive_failures: int = 0
        self._events_history: list[OrchestratorEvent] = []

    @property
    def current_state(self) -> StateEnum:
        """Estado actual de la máquina."""
        return self._state

    @property
    def consecutive_failures(self) -> int:
        """Número acumulado de fallos consecutivos en N1."""
        return self._consecutive_failures

    @property
    def events_history(self) -> list[OrchestratorEvent]:
        """Historial de eventos emitidos en memoria."""
        return list(self._events_history)

    def transition_to(
        self,
        target_state: StateEnum,
        event_name: str,
        details: dict[str, Any] | None = None,
    ) -> OrchestratorEvent:
        """Aplica una transición de estado si está permitida y emite un evento formal."""
        allowed = self.ALLOWED_TRANSITIONS.get(self._state, set())
        if target_state not in allowed:
            raise InvalidStateTransitionError(
                f"Transición inválida de {self._state.value} a {target_state.value}"
            )

        event = OrchestratorEvent(
            name=event_name,
            from_state=self._state,
            to_state=target_state,
            timestamp_ns=self.clock.now_ns(),
            details=details or {},
        )
        self._state = target_state
        self._events_history.append(event)
        return event

    def process_probe_results(
        self,
        results: list[ProbeResult],
    ) -> tuple[StateEnum, list[OrchestratorEvent]]:
        """Evalúa una ronda de sondas hacia N1 y actualiza contadores y estados."""
        events: list[OrchestratorEvent] = []

        # Histéresis: si ya estamos conmutando o conmutados, ignorar nuevas decisiones de failover
        if self._state in (StateEnum.FAILING_OVER, StateEnum.FAILED_OVER, StateEnum.FAILOVER_ERROR):
            return self._state, events

        if not results:
            return self._state, events

        # N1 se considera caída únicamente si TODAS las instancias configuradas fallaron
        all_failed = all(not r.is_healthy for r in results)

        if not all_failed:
            # Al menos una instancia está completamente sana: éxito intermedio reinicia contador
            if self._consecutive_failures > 0 or self._state == StateEnum.SUSPECT:
                prev_state = self._state
                self._consecutive_failures = 0
                if prev_state == StateEnum.SUSPECT:
                    event = self.transition_to(
                        StateEnum.HEALTHY,
                        event_name="state_recovered",
                        details={"reason": "Instancia N1 sana recuperada; contador reiniciado a 0"},
                    )
                    events.append(event)
            return self._state, events

        # Todas las instancias fallaron en esta ronda
        self._consecutive_failures += 1
        now_ns = self.clock.now_ns()

        events.append(
            OrchestratorEvent(
                name="probe_failed",
                from_state=self._state,
                to_state=self._state,
                timestamp_ns=now_ns,
                details={
                    "consecutive_failures": self._consecutive_failures,
                    "threshold": self.failure_threshold,
                    "probes": [r.model_dump() for r in results],
                },
            )
        )

        if self._consecutive_failures < self.failure_threshold:
            if self._state == StateEnum.HEALTHY:
                event = self.transition_to(
                    StateEnum.SUSPECT,
                    event_name="suspect",
                    details={"consecutive_failures": self._consecutive_failures},
                )
                events.append(event)
        else:
            # Se alcanzó o superó el umbral exacto de 3 fallos consecutivos
            event = self.transition_to(
                StateEnum.FAILING_OVER,
                event_name="t_detect",
                details={
                    "consecutive_failures": self._consecutive_failures,
                    "reason": f"Alcanzado umbral de {self.failure_threshold} fallos consecutivos en N1",
                },
            )
            events.append(event)

        return self._state, events

    def reset(self) -> OrchestratorEvent:
        """Reinicia la máquina de estados a HEALTHY y limpia contadores."""
        prev = self._state
        self._state = StateEnum.HEALTHY
        self._consecutive_failures = 0
        event = OrchestratorEvent(
            name="reset",
            from_state=prev,
            to_state=StateEnum.HEALTHY,
            timestamp_ns=self.clock.now_ns(),
            details={"action": "reinicio administrativo explícito"},
        )
        self._events_history.append(event)
        return event

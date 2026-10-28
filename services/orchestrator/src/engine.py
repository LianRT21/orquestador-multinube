"""Motor de orquestación de resiliencia: coordinación de sondas, FSM y conmutación atómica."""

import asyncio

import structlog

from services.orchestrator.src.adapters.haproxy import HAProxyAdapterProtocol, HAProxySocketClient
from services.orchestrator.src.adapters.postgres import (
    AsyncpgPostgresPromoter,
    PostgresPromoterProtocol,
)
from services.orchestrator.src.adapters.probe import HttpxProbeClient, ProbeClientProtocol
from services.orchestrator.src.clock import ClockProtocol, SystemClock
from services.orchestrator.src.config import OrchestratorSettings, orchestrator_settings
from services.orchestrator.src.models import OrchestratorEvent, ProbeResult, StateEnum
from services.orchestrator.src.state_machine import FailoverStateMachine

logger = structlog.get_logger()


class OrchestratorEngine:
    """Coordinador principal de detección, fencing, promoción y conmutación de proxy."""

    def __init__(
        self,
        settings: OrchestratorSettings | None = None,
        clock: ClockProtocol | None = None,
        state_machine: FailoverStateMachine | None = None,
        haproxy_client: HAProxyAdapterProtocol | None = None,
        postgres_promoter: PostgresPromoterProtocol | None = None,
        probe_client: ProbeClientProtocol | None = None,
    ) -> None:
        self.settings = settings or orchestrator_settings
        self.clock = clock or SystemClock()
        self.state_machine = state_machine or FailoverStateMachine(
            clock=self.clock,
            failure_threshold=self.settings.FAILURE_THRESHOLD,
        )
        self.haproxy = haproxy_client or HAProxySocketClient(
            host=self.settings.HAPROXY_HOST,
            port=self.settings.HAPROXY_PORT,
        )
        self.postgres = postgres_promoter or AsyncpgPostgresPromoter()
        self.probe = probe_client or HttpxProbeClient()

        self.active_cloud: str = "cloud_a"
        self.last_rto_seconds: float | None = None
        self.t_detect_ns: int | None = None
        self._failover_lock = asyncio.Lock()
        self._all_events: list[OrchestratorEvent] = []

    def _record_event(self, event: OrchestratorEvent) -> None:
        """Almacena el evento en la lista consolidada."""
        self._all_events.append(event)
        logger.info(
            "Evento emitido por el orquestador",
            event_name=event.name,
            from_state=event.from_state.value,
            to_state=event.to_state.value,
            timestamp_ns=event.timestamp_ns,
            details=event.details,
        )

    async def run_probe_cycle(self) -> list[OrchestratorEvent]:
        """Ejecuta una ronda concurrente de sondas sobre N1 y procesa el resultado en la FSM."""
        # Sondeo concurrente a todas las instancias configuradas de N1
        probe_tasks = [
            self.probe.probe_endpoint(
                url=url,
                timeout_s=self.settings.PROBE_TIMEOUT_S,
                degraded_latency_ms=self.settings.DEGRADED_LATENCY_MS,
            )
            for url in self.settings.N1_HEALTH_URLS
        ]
        results: list[ProbeResult] = await asyncio.gather(*probe_tasks)

        # Evaluar resultados en la máquina de estados
        _, new_events = self.state_machine.process_probe_results(results)
        for ev in new_events:
            self._record_event(ev)

        # Si la FSM transicionó a FAILING_OVER, disparar conmutación
        if self.state_machine.current_state == StateEnum.FAILING_OVER:
            # Buscar marca de tiempo de t_detect
            detect_event = next((e for e in new_events if e.name == "t_detect"), None)
            if detect_event:
                self.t_detect_ns = detect_event.timestamp_ns
            else:
                self.t_detect_ns = self.clock.now_ns()

            await self.execute_failover()

        return new_events

    async def execute_failover(self) -> bool:
        """Secuencia idempotente y atómica de failover (fencing -> promote -> switch -> verify)."""
        async with self._failover_lock:
            # Si ya está conmutado o en error, no ejecutar concurrentemente
            if self.state_machine.current_state in (
                StateEnum.FAILED_OVER,
                StateEnum.FAILOVER_ERROR,
            ):
                return False

            if self.t_detect_ns is None:
                self.t_detect_ns = self.clock.now_ns()

            logger.info(
                "Iniciando secuencia atómica de failover hacia N2", t_detect_ns=self.t_detect_ns
            )

            try:
                # --------------------------------------------------------------
                # Paso 1: Fencing de N1 en el Proxy (sacar app-a a maint)
                # --------------------------------------------------------------
                await self.haproxy.set_server_state(
                    backend=self.settings.HAPROXY_BACKEND,
                    server=self.settings.HAPROXY_SERVER_A,
                    state="maint",
                )
                self._record_event(
                    OrchestratorEvent(
                        name="t_fence",
                        from_state=self.state_machine.current_state,
                        to_state=self.state_machine.current_state,
                        timestamp_ns=self.clock.now_ns(),
                        details={
                            "server": self.settings.HAPROXY_SERVER_A,
                            "action": "set_state_maint",
                        },
                    )
                )

                # Intento adicional de solo lectura en db-a si aún es alcanzable
                await self.postgres.set_read_only(
                    host="db-a",
                    port=5432,
                    user=self.settings.POSTGRES_USER,
                    password=self.settings.POSTGRES_PASSWORD,
                    dbname=self.settings.POSTGRES_DB,
                    timeout_s=1.0,
                )

                # --------------------------------------------------------------
                # Paso 2: Pre-flight check en N2 (verificar app-b y db-b sana)
                # --------------------------------------------------------------
                n2_url = self.settings.N2_HEALTH_URLS[0]
                n2_probe = await self.probe.probe_endpoint(
                    url=n2_url,
                    timeout_s=2.0,
                    degraded_latency_ms=self.settings.DEGRADED_LATENCY_MS,
                )
                if not n2_probe.db_ok:
                    raise RuntimeError(
                        f"Nube secundaria N2 no está disponible para failover: {n2_probe.error_message}"
                    )

                # --------------------------------------------------------------
                # Paso 3: Promoción de la réplica db-b
                # --------------------------------------------------------------
                t_promote_start = self.clock.now_ns()
                self._record_event(
                    OrchestratorEvent(
                        name="t_promote_start",
                        from_state=self.state_machine.current_state,
                        to_state=self.state_machine.current_state,
                        timestamp_ns=t_promote_start,
                        details={"target_db": self.settings.DB_B_HOST},
                    )
                )

                promote_duration_ms = await self.postgres.promote_replica(
                    host=self.settings.DB_B_HOST,
                    port=self.settings.DB_B_PORT,
                    user=self.settings.POSTGRES_USER,
                    password=self.settings.POSTGRES_PASSWORD,
                    dbname=self.settings.POSTGRES_DB,
                )

                t_promote_end = self.clock.now_ns()
                self._record_event(
                    OrchestratorEvent(
                        name="t_promote_end",
                        from_state=self.state_machine.current_state,
                        to_state=self.state_machine.current_state,
                        timestamp_ns=t_promote_end,
                        details={"duration_ms": promote_duration_ms},
                    )
                )

                # --------------------------------------------------------------
                # Paso 4: Redirección del Proxy a N2 (habilitar app-b en ready)
                # --------------------------------------------------------------
                await self.haproxy.set_server_state(
                    backend=self.settings.HAPROXY_BACKEND,
                    server=self.settings.HAPROXY_SERVER_B,
                    state="ready",
                )
                t_switch = self.clock.now_ns()
                self.active_cloud = "cloud_b"
                self._record_event(
                    OrchestratorEvent(
                        name="t_switch",
                        from_state=self.state_machine.current_state,
                        to_state=self.state_machine.current_state,
                        timestamp_ns=t_switch,
                        details={"active_server": self.settings.HAPROXY_SERVER_B},
                    )
                )

                # --------------------------------------------------------------
                # Paso 5: Verificación sintética post-conmutación
                # --------------------------------------------------------------
                verified = await self.probe.verify_order_flow(self.settings.PROXY_ORDERS_URL)
                t_verified = self.clock.now_ns()

                if not verified:
                    logger.warn("Verificación sintética falló o tuvo advertencias tras el switch")

                self._record_event(
                    OrchestratorEvent(
                        name="t_verified",
                        from_state=self.state_machine.current_state,
                        to_state=self.state_machine.current_state,
                        timestamp_ns=t_verified,
                        details={"verified_ok": verified},
                    )
                )

                # Calcular RTO experimental preliminar
                self.last_rto_seconds = round((t_verified - self.t_detect_ns) / 1_000_000_000.0, 3)

                # --------------------------------------------------------------
                # Paso 6: Transición final a FAILED_OVER
                # --------------------------------------------------------------
                final_event = self.state_machine.transition_to(
                    StateEnum.FAILED_OVER,
                    event_name="failed_over",
                    details={
                        "rto_seconds": self.last_rto_seconds,
                        "t_detect_ns": self.t_detect_ns,
                        "t_switch_ns": t_switch,
                        "t_verified_ns": t_verified,
                    },
                )
                self._record_event(final_event)
                logger.info(
                    "Conmutación por error completada exitosamente",
                    rto_seconds=self.last_rto_seconds,
                )
                return True

            except Exception as exc:
                logger.error("Error durante la secuencia de conmutación", error=str(exc))
                error_event = self.state_machine.transition_to(
                    StateEnum.FAILOVER_ERROR,
                    event_name="failover_error",
                    details={"error": str(exc)},
                )
                self._record_event(error_event)
                return False

    def reset(self) -> OrchestratorEvent:
        """Reinicia el orquestador al estado HEALTHY inicial."""
        self.active_cloud = "cloud_a"
        self.last_rto_seconds = None
        self.t_detect_ns = None
        reset_ev = self.state_machine.reset()
        self._record_event(reset_ev)
        logger.info("Orquestador reiniciado a estado HEALTHY")
        return reset_ev

    def get_all_events(self) -> list[OrchestratorEvent]:
        """Retorna todos los eventos registrados cronológicamente."""
        return list(self._all_events)

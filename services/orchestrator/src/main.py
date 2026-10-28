"""API REST de administración y plano de control del Orquestador de Resiliencia."""

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import structlog
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from fastapi.responses import Response as PlainResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

from services.orchestrator.src.config import orchestrator_settings
from services.orchestrator.src.engine import OrchestratorEngine
from services.orchestrator.src.models import OrchestratorEvent, StateEnum, StatusResponse

logger = structlog.get_logger()
APP_START_TIME = time.time()

# Métricas Prometheus del Orquestador
ORCHESTRATOR_STATE_CODE = Gauge(
    "orchestrator_state_code",
    "Código del estado actual de la FSM (0=HEALTHY, 1=SUSPECT, 2=FAILING_OVER, 3=FAILED_OVER, 4=FAILOVER_ERROR)",
)
ORCHESTRATOR_CONSECUTIVE_FAILURES = Gauge(
    "orchestrator_consecutive_failures",
    "Contador de fallos consecutivos observados en la nube activa",
)
ORCHESTRATOR_LAST_RTO_SECONDS = Gauge(
    "orchestrator_last_rto_seconds",
    "Último RTO calculado en segundos por el orquestador",
)
ORCHESTRATOR_PROBE_LATENCY_MS = Gauge(
    "orchestrator_probe_latency_ms",
    "Latencia de la última sonda enviada a N1 en milisegundos",
)
ORCHESTRATOR_EVENTS_TOTAL = Counter(
    "orchestrator_events_total",
    "Total de eventos emitidos por el orquestador",
    ["event_name"],
)

STATE_MAP: dict[StateEnum, int] = {
    StateEnum.HEALTHY: 0,
    StateEnum.SUSPECT: 1,
    StateEnum.FAILING_OVER: 2,
    StateEnum.FAILED_OVER: 3,
    StateEnum.FAILOVER_ERROR: 4,
}

engine = OrchestratorEngine(settings=orchestrator_settings)


def persist_event_jsonl(event: OrchestratorEvent, filepath: str) -> None:
    """Persiste el evento en un archivo JSON Lines para auditoría del runner experimental."""
    try:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.model_dump()) + "\n")
    except Exception as exc:
        logger.error("No se pudo escribir el evento en JSON Lines", error=str(exc), path=filepath)


# Interceptar eventos para métricas y persistencia
_orig_record_event = engine._record_event


def _wrapped_record_event(event: OrchestratorEvent) -> None:
    _orig_record_event(event)
    ORCHESTRATOR_EVENTS_TOTAL.labels(event_name=event.name).inc()
    ORCHESTRATOR_STATE_CODE.set(STATE_MAP.get(event.to_state, -1))
    persist_event_jsonl(event, engine.settings.EVENTS_LOG_PATH)


engine._record_event = _wrapped_record_event  # type: ignore[method-assign]


async def probe_background_worker(engine_instance: OrchestratorEngine) -> None:
    """Bucle en segundo plano que sondea N1 según el intervalo configurado."""
    logger.info("Iniciando bucle de sondas del orquestador")
    while True:
        try:
            await engine_instance.run_probe_cycle()
            current_state = engine_instance.state_machine.current_state
            ORCHESTRATOR_STATE_CODE.set(STATE_MAP.get(current_state, 0))
            ORCHESTRATOR_CONSECUTIVE_FAILURES.set(
                engine_instance.state_machine.consecutive_failures
            )

            if engine_instance.last_rto_seconds is not None:
                ORCHESTRATOR_LAST_RTO_SECONDS.set(engine_instance.last_rto_seconds)

            # Pausa hasta el próximo ciclo
            await asyncio.sleep(engine_instance.settings.PROBE_INTERVAL_S)
        except asyncio.CancelledError:
            logger.info("Deteniendo bucle de sondas del orquestador")
            break
        except Exception as exc:
            logger.error("Error no controlado en el ciclo de sondas", error=str(exc))
            await asyncio.sleep(engine_instance.settings.PROBE_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Gestiona el ciclo de vida del servicio y la tarea en segundo plano."""
    worker_task = asyncio.create_task(probe_background_worker(engine))
    yield
    worker_task.cancel()
    with suppress(asyncio.CancelledError):
        await worker_task


app = FastAPI(
    title="Multi-Cloud Resilience Failover Orchestrator",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/status", response_model=StatusResponse, summary="Estado actual del orquestador")
async def get_status() -> StatusResponse:
    """Devuelve el estado formal de la FSM, contadores y parámetros."""
    return StatusResponse(
        current_state=engine.state_machine.current_state,
        consecutive_failures=engine.state_machine.consecutive_failures,
        failure_threshold=engine.settings.FAILURE_THRESHOLD,
        last_probe_timestamp_ns=engine.clock.now_ns(),
        active_cloud=engine.active_cloud,
        uptime_seconds=round(time.time() - APP_START_TIME, 2),
        total_events=len(engine.get_all_events()),
        last_rto_seconds=engine.last_rto_seconds,
    )


@app.get("/events", response_model=list[OrchestratorEvent], summary="Línea de tiempo de eventos")
async def get_events() -> list[OrchestratorEvent]:
    """Obtiene la secuencia histórica de eventos con timestamps en nanosegundos."""
    return engine.get_all_events()


@app.post("/reset", response_model=OrchestratorEvent, summary="Reinicio administrativo a HEALTHY")
async def reset_orchestrator() -> OrchestratorEvent:
    """Restablece el estado de la FSM a HEALTHY y limpia contadores."""
    reset_event = engine.reset()
    ORCHESTRATOR_STATE_CODE.set(STATE_MAP[StateEnum.HEALTHY])
    ORCHESTRATOR_CONSECUTIVE_FAILURES.set(0)
    return reset_event


@app.get("/health", summary="Chequeo de salud del servicio orquestador")
async def health() -> JSONResponse:
    """Verifica que el servicio esté respondiendo."""
    return JSONResponse(
        status_code=status.HTTP_200_OK, content={"status": "healthy", "service": "orchestrator"}
    )


@app.get("/metrics", summary="Métricas Prometheus del orquestador")
async def metrics() -> PlainResponse:
    """Expone métricas del orquestador para Prometheus."""
    return PlainResponse(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )

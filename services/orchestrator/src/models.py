"""Modelos de dominio, estados, eventos y tipos para el orquestador de resiliencia."""

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class StateEnum(StrEnum):
    """Estados formales de la Máquina de Estados Finita (FSM) del Orquestador."""

    HEALTHY = "HEALTHY"
    SUSPECT = "SUSPECT"
    FAILING_OVER = "FAILING_OVER"
    FAILED_OVER = "FAILED_OVER"
    FAILOVER_ERROR = "FAILOVER_ERROR"


class ProbeStatus(StrEnum):
    """Resultado individual de una sonda de salud HTTP."""

    OK = "OK"
    TIMEOUT = "TIMEOUT"
    HTTP_ERROR = "HTTP_ERROR"
    DEGRADED_LATENCY = "DEGRADED_LATENCY"
    DB_UNHEALTHY = "DB_UNHEALTHY"


class ProbeResult(BaseModel):
    """Resultado estructurado de una sonda concurrente."""

    model_config = ConfigDict(frozen=True)

    instance_url: str
    status: ProbeStatus
    status_code: int = 0
    latency_ms: float = 0.0
    db_ok: bool = False
    db_role: str = "unknown"
    error_message: str | None = None
    timestamp_ns: int = Field(default_factory=lambda: 0)

    @property
    def is_healthy(self) -> bool:
        """Determina si la instancia está completamente sana sin degradación."""
        return self.status == ProbeStatus.OK and self.db_ok and self.status_code == 200


class OrchestratorEvent(BaseModel):
    """Evento auditable emitido por el orquestador con marca temporal en nanosegundos."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(
        ..., description="Nombre del evento (p. ej. probe_failed, suspect, t_detect, t_switch)"
    )
    from_state: StateEnum
    to_state: StateEnum
    timestamp_ns: int = Field(..., description="Marca de tiempo UTC en nanosegundos")
    details: dict[str, Any] = Field(default_factory=dict)


class StatusResponse(BaseModel):
    """Esquema de respuesta para la API de administración GET /status."""

    current_state: StateEnum
    consecutive_failures: int
    failure_threshold: int
    last_probe_timestamp_ns: int
    active_cloud: str
    uptime_seconds: float
    total_events: int
    last_rto_seconds: float | None = None

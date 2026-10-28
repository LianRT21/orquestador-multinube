"""Modelos de datos y excepciones para el inyector de fallas."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class FaultType(StrEnum):
    """Tipos de fallas inyectadas en la nube primaria (N1)."""

    F1 = "F1"  # Caída de procesos de la aplicación (SIGKILL a app-a)
    F2 = "F2"  # Partición de red del plano de control (disconnect control_plane)
    F3 = "F3"  # Caída de base de datos primaria (SIGKILL a db-a)
    F4 = "F4"  # Degradación de red (tc netem delay 2000ms loss 20%)


class FaultResult(BaseModel):
    """Resultado de una operación de inyección de falla."""

    fault: FaultType
    t_fault_ns: int = Field(
        ...,
        description="Marca de tiempo UTC en nanosegundos inmediatamente antes de inyectar la falla",
    )
    success: bool
    details: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class RestoreResult(BaseModel):
    """Resultado de una operación de restauración de falla."""

    fault: FaultType
    t_restore_ns: int = Field(
        ...,
        description="Marca de tiempo UTC en nanosegundos inmediatamente antes de restaurar",
    )
    success: bool
    details: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class FaultInjectorConfig(BaseModel):
    """Configuración del inyector de fallas."""

    app_a_containers: list[str] = Field(
        default_factory=lambda: ["orquestador-app-a-1"],
        description="Lista de nombres o identificadores de contenedores de app-a",
    )
    control_plane_network: str = Field(
        default="orquestador_control_plane",
        description="Nombre de la red Docker del plano de control",
    )
    db_a_container: str = Field(
        default="orquestador-db-a-1",
        description="Nombre del contenedor de base de datos primaria db-a",
    )
    netem_target_container: str = Field(
        default="orquestador-app-a-1",
        description="Contenedor al cual aplicar tc netem en F4",
    )
    netem_delay_ms: int = Field(
        default=2000,
        description="Latencia adicional en milisegundos para F4",
    )
    netem_loss_pct: float = Field(
        default=20.0,
        description="Porcentaje de pérdida de paquetes para F4",
    )
    netem_interface: str = Field(
        default="eth0",
        description="Interfaz de red sobre la cual aplicar netem",
    )
    docker_base_url: str | None = Field(
        default=None,
        description="URL base del daemon de Docker o None para usar configuración por entorno",
    )


class FaultInjectorError(Exception):
    """Excepción base para errores del inyector de fallas."""


class FaultInjectionError(FaultInjectorError):
    """Error al inyectar una falla."""


class FaultRestoreError(FaultInjectorError):
    """Error al restaurar el estado tras una falla."""

"""Modelos de datos y esquemas de validación de la aplicación de referencia."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OrderCreate(BaseModel):
    """Esquema para la creación idempotente de pedidos."""

    model_config = ConfigDict(extra="forbid")

    order_id: UUID = Field(
        ...,
        description="Identificador único universal generado por el cliente para garantizar idempotencia",
    )
    customer_id: int = Field(..., gt=0, description="Identificador del cliente")
    amount: Decimal = Field(..., gt=0, decimal_places=2, description="Monto del pedido")


class OrderResponse(BaseModel):
    """Esquema de respuesta para pedidos consultados o confirmados."""

    model_config = ConfigDict(from_attributes=True)

    order_id: UUID
    customer_id: int
    amount: Decimal
    status: str
    seq: int
    committed_at: datetime


class HealthResponse(BaseModel):
    """Esquema detallado de salud del nodo y su base de datos asociada."""

    status: str = Field(..., description="'healthy' o 'unhealthy'")
    cloud_id: str = Field(..., description="Identificador de la nube (cloud_a o cloud_b)")
    db_ok: bool = Field(..., description="Verdadero si la base de datos responde exitosamente")
    db_role: str = Field(..., description="'primary', 'replica' o 'unknown'")
    db_latency_ms: float = Field(
        ..., description="Latencia en milisegundos de la consulta de verificación"
    )
    mem_mb: float = Field(..., description="Uso de memoria del proceso en megabytes")
    uptime_s: float = Field(..., description="Tiempo en segundos transcurrido desde el arranque")

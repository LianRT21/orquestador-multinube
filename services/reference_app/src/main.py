"""API REST transaccional de referencia con FastAPI y SQLAlchemy asíncrono."""

import os
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.responses import Response as PlainResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.reference_app.src.config import settings
from services.reference_app.src.database import OrderModel, db_manager
from services.reference_app.src.models import HealthResponse, OrderCreate, OrderResponse

# Configuración de métricas Prometheus
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total de solicitudes HTTP recibidas",
    ["method", "path", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "Histograma de latencia de solicitudes HTTP en segundos",
    ["method", "path"],
)
ORDERS_TOTAL = Counter(
    "orders_total",
    "Total de pedidos procesados por la aplicación",
    ["cloud_id", "outcome"],
)
DB_CONNECTED = Gauge(
    "app_db_connected",
    "Estado de conectividad a la base de datos (1=Conectado, 0=Error)",
    ["cloud_id"],
)
DB_IS_RECOVERY = Gauge(
    "app_db_is_recovery",
    "Indica si la base de datos está en modo recuperación/réplica (1=Réplica, 0=Primario)",
    ["cloud_id"],
)

logger = structlog.get_logger()
APP_START_TIME = time.time()


def get_memory_usage_mb() -> float:
    """Calcula el uso de memoria residente del proceso en MB de forma compatible."""
    try:
        import psutil

        process = psutil.Process(os.getpid())
        rss = float(process.memory_info().rss)
        return float(round(rss / (1024.0 * 1024.0), 2))
    except Exception:
        # Fallback sin dependencias adicionales
        return 0.0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Gestiona el ciclo de vida de la aplicación, inicio y drenado en SIGTERM."""
    logger.info("Iniciando aplicación de referencia", cloud_id=settings.CLOUD_ID)
    db_manager.init_engine()
    yield
    logger.info("Drenando conexiones y cerrando aplicación", cloud_id=settings.CLOUD_ID)
    await db_manager.close_engine()


app = FastAPI(
    title=f"Transactional Reference App - {settings.CLOUD_ID}",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def logging_and_metrics_middleware(request: Request, call_next: Any) -> Response:
    """Middleware para trazabilidad con request_id y captura de métricas Prometheus."""
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    request.state.request_id = request_id

    start_time = time.perf_counter()
    method = request.method
    path = request.url.path

    try:
        response: Response = await call_next(request)
        duration = time.perf_counter() - start_time

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Cloud-ID"] = settings.CLOUD_ID

        # No registrar métricas para scraping de prometheus o health para evitar ruido
        if path not in ("/metrics", "/health"):
            HTTP_REQUESTS_TOTAL.labels(
                method=method, path=path, status=str(response.status_code)
            ).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=path).observe(duration)

        return response
    except Exception as exc:
        duration = time.perf_counter() - start_time
        if path not in ("/metrics", "/health"):
            HTTP_REQUESTS_TOTAL.labels(method=method, path=path, status="500").inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=path).observe(duration)
        logger.error(
            "Error no controlado en solicitud",
            request_id=request_id,
            error=str(exc),
            path=path,
        )
        return JSONResponse(
            status_code=500,
            content={"error": "Internal Server Error", "request_id": request_id},
        )


@app.post(
    "/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crea un pedido con idempotencia garantizada por UUID del cliente",
)
async def create_order(
    payload: OrderCreate,
    response: Response,
    session: AsyncSession = Depends(db_manager.get_session),
) -> OrderResponse:
    """Crea un pedido si no existe; si ya existe el order_id responde 200 sin duplicar."""
    # Verificar si la base de datos está en modo réplica
    role = await db_manager.check_role()
    if role == "replica":
        logger.warn("Escritura rechazada: BD en modo réplica", cloud_id=settings.CLOUD_ID)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La base de datos se encuentra en modo réplica de solo lectura.",
        )

    # Comprobación de idempotencia: consultar si ya existe el order_id
    existing_order = await session.get(OrderModel, payload.order_id)
    if existing_order is not None:
        response.status_code = status.HTTP_200_OK
        ORDERS_TOTAL.labels(cloud_id=settings.CLOUD_ID, outcome="idempotent_duplicate").inc()
        return OrderResponse.model_validate(existing_order)

    # Crear nueva orden
    new_order = OrderModel(
        order_id=payload.order_id,
        customer_id=payload.customer_id,
        amount=payload.amount,
        status="COMPLETED",
    )
    session.add(new_order)

    try:
        await session.commit()
        await session.refresh(new_order)
        ORDERS_TOTAL.labels(cloud_id=settings.CLOUD_ID, outcome="created").inc()
        return OrderResponse.model_validate(new_order)
    except IntegrityError:
        # Manejo de condición de carrera concurrente con la misma clave primaria
        await session.rollback()
        existing = await session.get(OrderModel, payload.order_id)
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            ORDERS_TOTAL.labels(cloud_id=settings.CLOUD_ID, outcome="idempotent_duplicate").inc()
            return OrderResponse.model_validate(existing)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al procesar la transacción concurrente.",
        ) from None


@app.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
    summary="Consulta un pedido por su UUID",
)
async def get_order(
    order_id: UUID,
    session: AsyncSession = Depends(db_manager.get_session),
) -> OrderResponse:
    """Obtiene un pedido existente."""
    order = await session.get(OrderModel, order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pedido no encontrado.",
        )
    return OrderResponse.model_validate(order)


@app.get(
    "/orders",
    response_model=list[OrderResponse],
    summary="Consulta pedidos con filtro por cliente y límite",
)
async def list_orders(
    customer_id: int | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(db_manager.get_session),
) -> list[OrderResponse]:
    """Lista pedidos filtrados."""
    query = select(OrderModel)
    if customer_id is not None:
        query = query.where(OrderModel.customer_id == customer_id)
    query = query.order_by(OrderModel.seq.desc()).limit(min(limit, 100))

    result = await session.execute(query)
    orders = result.scalars().all()
    return [OrderResponse.model_validate(o) for o in orders]


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Verificación profunda de salud del nodo y rol de BD",
)
async def health_check() -> JSONResponse:
    """Evalúa la conexión real a PostgreSQL y determina el rol del nodo."""
    db_ok, db_role, latency_ms = await db_manager.check_health()
    mem_mb = get_memory_usage_mb()
    uptime_s = round(time.time() - APP_START_TIME, 2)

    # Actualizar métricas gauge
    DB_CONNECTED.labels(cloud_id=settings.CLOUD_ID).set(1.0 if db_ok else 0.0)
    DB_IS_RECOVERY.labels(cloud_id=settings.CLOUD_ID).set(1.0 if db_role == "replica" else 0.0)

    data = {
        "status": "healthy" if db_ok else "unhealthy",
        "cloud_id": settings.CLOUD_ID,
        "db_ok": db_ok,
        "db_role": db_role,
        "db_latency_ms": latency_ms,
        "mem_mb": mem_mb,
        "uptime_s": uptime_s,
    }

    status_code = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=data)


@app.get("/metrics", summary="Métricas de observabilidad Prometheus")
async def metrics() -> PlainResponse:
    """Expone métricas en formato estándar de Prometheus."""
    return PlainResponse(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )

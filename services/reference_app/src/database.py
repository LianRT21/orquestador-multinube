"""Manejo de base de datos asíncrona, esquema relacional y monitoreo de rol."""

import time
from collections.abc import AsyncGenerator
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from services.reference_app.src.config import settings


class Base(DeclarativeBase):
    """Clase base declarativa de SQLAlchemy."""

    pass


class OrderModel(Base):
    """Entidad relacional de pedidos."""

    __tablename__ = "orders"

    order_id: Mapped[UUID] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="COMPLETED")
    seq: Mapped[int] = mapped_column(BigInteger, autoincrement=True, index=True)
    committed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        nullable=False,
    )


class DatabaseManager:
    """Gestor de conexiones asíncronas y evaluación de salud de PostgreSQL."""

    def __init__(self, db_url: str | None = None) -> None:
        self.url = db_url or settings.DATABASE_URL
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

        # Caché de rol (TTL configurable para responder a promociones en < 1s)
        self._cached_role: str = "unknown"
        self._last_role_check: float = 0.0

    def init_engine(self) -> None:
        """Inicializa el motor asíncrono con pool de conexiones configurado."""
        if self._engine is None:
            connect_args: dict[str, Any] = {}
            if "asyncpg" in self.url:
                connect_args["command_timeout"] = settings.DB_TIMEOUT_SECONDS
                connect_args["timeout"] = settings.DB_TIMEOUT_SECONDS

            self._engine = create_async_engine(
                self.url,
                pool_size=settings.DB_POOL_SIZE,
                max_overflow=settings.DB_MAX_OVERFLOW,
                pool_pre_ping=True,
                connect_args=connect_args,
            )
            self._sessionmaker = async_sessionmaker(
                bind=self._engine,
                expire_on_commit=False,
            )

    async def close_engine(self) -> None:
        """Cierra ordenadamente el motor y el pool de conexiones."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessionmaker = None

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Generador de sesiones asíncronas para inyección de dependencias."""
        if self._sessionmaker is None:
            self.init_engine()
        assert self._sessionmaker is not None
        async with self._sessionmaker() as session:
            yield session

    async def check_role(self, force_refresh: bool = False) -> str:
        """Determina si la base de datos es 'primary' o 'replica' respetando la caché TTL."""
        now = time.monotonic()
        if not force_refresh and (now - self._last_role_check < settings.ROLE_CACHE_TTL_SECONDS):
            return self._cached_role

        if self._engine is None:
            self.init_engine()
        assert self._engine is not None

        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(text("SELECT pg_is_in_recovery()"))
                is_recovery: bool = bool(result.scalar())
                self._cached_role = "replica" if is_recovery else "primary"
                self._last_role_check = now
                return self._cached_role
        except Exception:
            return "unknown"

    async def check_health(self) -> tuple[bool, str, float]:
        """Ejecuta una consulta real (SELECT 1, pg_is_in_recovery()) y mide la latencia."""
        if self._engine is None:
            self.init_engine()
        assert self._engine is not None

        start = time.perf_counter()
        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(text("SELECT 1, pg_is_in_recovery()"))
                row = result.first()
                latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
                if row and row[0] == 1:
                    is_recovery: bool = bool(row[1])
                    role = "replica" if is_recovery else "primary"
                    self._cached_role = role
                    self._last_role_check = time.monotonic()
                    return True, role, latency_ms
                return False, "unknown", latency_ms
        except Exception:
            latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
            return False, "unknown", latency_ms


db_manager = DatabaseManager()

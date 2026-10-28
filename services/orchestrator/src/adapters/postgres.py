"""Adaptador para administración y promoción de PostgreSQL."""

import time
from typing import Protocol

import asyncpg
import structlog

logger = structlog.get_logger()


class PostgresPromoterProtocol(Protocol):
    """Protocolo de interfaz para promoción de PostgreSQL."""

    async def promote_replica(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        dbname: str,
        timeout_s: float = 60.0,
    ) -> float:
        """Promueve la réplica y retorna la duración en milisegundos."""
        ...

    async def set_read_only(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        dbname: str,
        timeout_s: float = 2.0,
    ) -> bool:
        """Intento de aislar la primaria antigua poniéndola en solo lectura."""
        ...


class AsyncpgPostgresPromoter:
    """Implementación real de promoción mediante asyncpg."""

    async def promote_replica(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        dbname: str,
        timeout_s: float = 60.0,
    ) -> float:
        """Ejecuta SELECT pg_promote(wait => true) y mide el tiempo exacto."""
        start = time.perf_counter()
        logger.info(
            "Iniciando promoción de réplica PostgreSQL", host=host, port=port, dbname=dbname
        )

        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=dbname,
            timeout=timeout_s,
        )
        try:
            # pg_promote(wait => true, wait_seconds => ...)
            result = await conn.fetchval("SELECT pg_promote(wait => true, wait_seconds => 60);")
            duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
            logger.info(
                "Promoción de PostgreSQL finalizada exitosamente",
                result=result,
                duration_ms=duration_ms,
            )
            return duration_ms
        finally:
            await conn.close()

    async def set_read_only(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        dbname: str,
        timeout_s: float = 2.0,
    ) -> bool:
        """Intenta colocar default_transaction_read_only en 'on' para fencing de N1."""
        try:
            conn = await asyncpg.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=dbname,
                timeout=timeout_s,
            )
            try:
                await conn.execute("ALTER SYSTEM SET default_transaction_read_only = 'on';")
                await conn.execute("SELECT pg_reload_conf();")
                logger.info("Fencing de base de datos primaria N1 aplicado (read-only)", host=host)
                return True
            finally:
                await conn.close()
        except Exception as exc:
            logger.warn(
                "No se pudo aplicar read-only a la primaria antigua (esperado si está caída)",
                error=str(exc),
            )
            return False

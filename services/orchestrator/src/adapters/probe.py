"""Adaptador asíncrono de sondeo HTTP y verificación sintética."""

import time
from typing import Protocol
from uuid import uuid4

import httpx
import structlog

from services.orchestrator.src.models import ProbeResult, ProbeStatus

logger = structlog.get_logger()


class ProbeClientProtocol(Protocol):
    """Protocolo de cliente de sondeo de salud."""

    async def probe_endpoint(
        self,
        url: str,
        timeout_s: float,
        degraded_latency_ms: float = 1500.0,
    ) -> ProbeResult:
        """Ejecuta una sonda HTTP GET a un endpoint /health."""
        ...

    async def verify_order_flow(
        self,
        orders_url: str,
        timeout_s: float = 3.0,
    ) -> bool:
        """Ejecuta una transacción sintética (POST + GET) para verificación de conmutación."""
        ...


class HttpxProbeClient:
    """Implementación de sondas HTTP utilizando httpx asíncrono."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def close(self) -> None:
        """Cierra el cliente HTTP si fue instanciado internamente."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def probe_endpoint(
        self,
        url: str,
        timeout_s: float,
        degraded_latency_ms: float = 1500.0,
    ) -> ProbeResult:
        """Consulta el endpoint /health y detecta timeouts, 5xx y degradación de latencia."""
        client = await self._get_client()
        start = time.perf_counter()
        now_ns = time.time_ns()

        try:
            response = await client.get(url, timeout=timeout_s)
            latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
            status_code = response.status_code

            # Caso 1: Código HTTP diferente de 200
            if status_code != 200:
                return ProbeResult(
                    instance_url=url,
                    status=ProbeStatus.HTTP_ERROR,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    error_message=f"HTTP {status_code}",
                    timestamp_ns=now_ns,
                )

            # Caso 2: Latencia degradada (Gray Failure F4)
            if latency_ms >= degraded_latency_ms:
                return ProbeResult(
                    instance_url=url,
                    status=ProbeStatus.DEGRADED_LATENCY,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    error_message=f"Latencia {latency_ms}ms >= umbral {degraded_latency_ms}ms",
                    timestamp_ns=now_ns,
                )

            # Caso 3: Parsear JSON de salud
            data = response.json()
            db_ok = bool(data.get("db_ok", False))
            db_role = str(data.get("db_role", "unknown"))

            if not db_ok:
                return ProbeResult(
                    instance_url=url,
                    status=ProbeStatus.DB_UNHEALTHY,
                    status_code=status_code,
                    latency_ms=latency_ms,
                    db_ok=False,
                    db_role=db_role,
                    error_message="Base de datos interna reportó db_ok=False",
                    timestamp_ns=now_ns,
                )

            return ProbeResult(
                instance_url=url,
                status=ProbeStatus.OK,
                status_code=status_code,
                latency_ms=latency_ms,
                db_ok=True,
                db_role=db_role,
                timestamp_ns=now_ns,
            )

        except httpx.TimeoutException:
            latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
            return ProbeResult(
                instance_url=url,
                status=ProbeStatus.TIMEOUT,
                latency_ms=latency_ms,
                error_message=f"Timeout superó {timeout_s}s",
                timestamp_ns=now_ns,
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
            return ProbeResult(
                instance_url=url,
                status=ProbeStatus.HTTP_ERROR,
                latency_ms=latency_ms,
                error_message=str(exc),
                timestamp_ns=now_ns,
            )

    async def verify_order_flow(
        self,
        orders_url: str,
        timeout_s: float = 3.0,
    ) -> bool:
        """Ejecuta una transacción sintética (POST + GET) a través del proxy para verificar N2."""
        client = await self._get_client()
        test_id = str(uuid4())
        payload = {
            "order_id": test_id,
            "customer_id": 999999,
            "amount": "1.00",
        }

        try:
            # 1. Escritura de prueba
            post_resp = await client.post(orders_url, json=payload, timeout=timeout_s)
            if post_resp.status_code not in (200, 201):
                logger.error(
                    "Verificación sintética falló en POST",
                    status=post_resp.status_code,
                    text=post_resp.text,
                )
                return False

            # 2. Lectura de prueba
            get_resp = await client.get(f"{orders_url}/{test_id}", timeout=timeout_s)
            if get_resp.status_code != 200:
                logger.error("Verificación sintética falló en GET", status=get_resp.status_code)
                return False

            logger.info("Verificación sintética post-failover exitosa a través del proxy")
            return True
        except Exception as exc:
            logger.error("Excepción en verificación sintética post-failover", error=str(exc))
            return False

"""Abstracción inyectable de reloj para determinismo en pruebas unitarias y precisión temporal."""

import asyncio
import time
from typing import Protocol


class ClockProtocol(Protocol):
    """Protocolo de reloj para medición y marcas de tiempo."""

    def now_ns(self) -> int:
        """Retorna la marca de tiempo actual en nanosegundos UTC."""
        ...

    def now_s(self) -> float:
        """Retorna la marca de tiempo actual en segundos UTC."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Pausa asíncrona inyectable."""
        ...


class SystemClock:
    """Implementación real basada en el reloj del sistema operativo."""

    def now_ns(self) -> int:
        return time.time_ns()

    def now_s(self) -> float:
        return time.time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class MockClock:
    """Reloj simulado para pruebas unitarias deterministas sin esperas reales."""

    def __init__(self, start_ns: int = 1_700_000_000_000_000_000) -> None:
        self._current_ns = start_ns

    def now_ns(self) -> int:
        return self._current_ns

    def now_s(self) -> float:
        return self._current_ns / 1_000_000_000.0

    def advance(self, seconds: float) -> None:
        """Avanza manualmente el reloj simulado."""
        self._current_ns += int(seconds * 1_000_000_000)

    def set_ns(self, timestamp_ns: int) -> None:
        """Fija la marca de tiempo exacta en nanosegundos."""
        self._current_ns = timestamp_ns

    async def sleep(self, seconds: float) -> None:
        """Avanza el reloj inmediatamente sin bloquear el hilo de ejecución."""
        self.advance(seconds)

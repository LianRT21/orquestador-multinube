"""Adaptador asíncrono para administración de HAProxy mediante Runtime API (socket TCP)."""

import asyncio
from typing import Protocol

import structlog

logger = structlog.get_logger()


class HAProxyClientError(Exception):
    """Excepción base para errores de comunicación con HAProxy Runtime API."""

    pass


class HAProxyAdapterProtocol(Protocol):
    """Interfaz abstracta del adaptador de HAProxy para inyección de dependencias."""

    async def set_server_state(self, backend: str, server: str, state: str) -> bool:
        """Modifica el estado administrativo de un servidor (ready, maint, drain)."""
        ...

    async def get_server_state(self, backend: str, server: str) -> str:
        """Obtiene el estado administrativo actual de un servidor en un backend."""
        ...

    async def ping(self) -> bool:
        """Verifica la conectividad con el socket de control de HAProxy."""
        ...


class HAProxySocketClient:
    """Implementación real de la Runtime API de HAProxy sobre socket TCP asíncrono."""

    def __init__(self, host: str = "haproxy", port: int = 9999, timeout: float = 2.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    async def send_command(self, command: str) -> str:
        """Envía un comando al socket TCP de HAProxy y retorna la respuesta."""
        clean_command = command.strip() + "\n"
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
            writer.write(clean_command.encode("utf-8"))
            await writer.drain()

            raw_response = await asyncio.wait_for(
                reader.read(-1),
                timeout=self.timeout,
            )
            writer.close()
            await writer.wait_closed()
            return raw_response.decode("utf-8").strip()
        except TimeoutError as err:
            logger.error(
                "Timeout comunicando con HAProxy Runtime API", host=self.host, port=self.port
            )
            raise HAProxyClientError(
                f"Timeout al enviar comando a HAProxy: {clean_command.strip()}"
            ) from err
        except OSError as err:
            logger.error(
                "Error de socket comunicando con HAProxy",
                error=str(err),
                host=self.host,
                port=self.port,
            )
            raise HAProxyClientError(f"Error de red con HAProxy: {err}") from err

    async def set_server_state(self, backend: str, server: str, state: str) -> bool:
        """Establece el estado de un servidor ('ready', 'maint', 'drain')."""
        valid_states = {"ready", "maint", "drain"}
        state_lower = state.lower()
        if state_lower not in valid_states:
            raise ValueError(f"Estado inválido '{state}'. Debe ser uno de {valid_states}")

        cmd = f"set server {backend}/{server} state {state_lower}"
        response = await self.send_command(cmd)

        # En HAProxy Runtime API, comandos exitosos retornan vacío o confirmación
        if "No such server" in response or "No such backend" in response:
            logger.error("Error en HAProxy al modificar servidor", response=response, cmd=cmd)
            raise HAProxyClientError(f"Fallo en HAProxy: {response}")

        logger.info(
            "Estado de servidor HAProxy modificado exitosamente",
            backend=backend,
            server=server,
            state=state_lower,
            response=response,
        )
        return True

    async def get_server_state(self, backend: str, server: str) -> str:
        """Consulta el estado del servidor leyendo la tabla de servidores."""
        cmd = f"show servers state {backend}"
        response = await self.send_command(cmd)

        for line in response.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue
            parts = line_str.split()
            # Formato estándar HAProxy: be_id be_name srv_id srv_name srv_addr srv_op_state srv_admin_state
            if len(parts) >= 7 and parts[3] == server:
                admin_state = parts[6]
                if admin_state in ("1", "2"):
                    return "maint"
                elif admin_state == "0":
                    return "ready"
                return admin_state
            elif len(parts) >= 4 and parts[0] == server:
                admin_state = parts[3]
                if admin_state in ("1", "2"):
                    return "maint"
                elif admin_state == "0":
                    return "ready"
                return admin_state
                return admin_state
        return "unknown"

    async def ping(self) -> bool:
        """Comprueba que el socket TCP de administración responde."""
        try:
            response = await self.send_command("show info")
            return "Name: HAProxy" in response or len(response) > 0
        except HAProxyClientError:
            return False

"""Pruebas unitarias del adaptador asíncrono de HAProxy Runtime API."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.orchestrator.src.adapters.haproxy import HAProxyClientError, HAProxySocketClient


def make_mock_writer() -> MagicMock:
    """Crea un doble de prueba para asyncio.StreamWriter con métodos síncronos adecuados."""
    writer = MagicMock()
    writer.write = MagicMock()
    writer.close = MagicMock()
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    return writer


@pytest.mark.asyncio
async def test_haproxy_set_server_state_success() -> None:
    """Verifica que el comando set server se envíe correctamente y retorne éxito."""
    client = HAProxySocketClient(host="127.0.0.1", port=9999)

    mock_reader = AsyncMock()
    mock_reader.read.return_value = b"\n"
    mock_writer = make_mock_writer()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        result = await client.set_server_state("app_back", "app-b", "ready")
        assert result is True
        mock_writer.write.assert_called_once_with(b"set server app_back/app-b state ready\n")


@pytest.mark.asyncio
async def test_haproxy_set_server_state_invalid() -> None:
    """Verifica que estados no permitidos levanten ValueError."""
    client = HAProxySocketClient()
    with pytest.raises(ValueError, match="Estado inválido"):
        await client.set_server_state("app_back", "app-b", "invalid_state")


@pytest.mark.asyncio
async def test_haproxy_server_not_found() -> None:
    """Verifica que un error de HAProxy ('No such server') levante HAProxyClientError."""
    client = HAProxySocketClient(host="127.0.0.1", port=9999)

    mock_reader = AsyncMock()
    mock_reader.read.return_value = b"No such server in backend.\n"
    mock_writer = make_mock_writer()

    with (
        patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)),
        pytest.raises(HAProxyClientError, match="No such server"),
    ):
        await client.set_server_state("app_back", "unknown-server", "maint")


@pytest.mark.asyncio
async def test_haproxy_get_server_state() -> None:
    """Verifica el parseo de la salida de 'show servers state'."""
    client = HAProxySocketClient(host="127.0.0.1", port=9999)

    mock_table = (
        b"1\n"
        b"# be_id be_name srv_id srv_name srv_addr srv_op_state srv_admin_state\n"
        b"1 app_back 1 app-a 172.28.0.2 2 0\n"
        b"1 app_back 2 app-b 172.28.0.3 2 1\n"
    )

    mock_reader = AsyncMock()
    mock_reader.read.return_value = mock_table
    mock_writer = make_mock_writer()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        state_a = await client.get_server_state("app_back", "app-a")
        assert state_a == "ready"

    mock_reader.read.return_value = mock_table
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        state_b = await client.get_server_state("app_back", "app-b")
        assert state_b == "maint"


@pytest.mark.asyncio
async def test_haproxy_ping() -> None:
    """Verifica la respuesta de ping al socket de control."""
    client = HAProxySocketClient(host="127.0.0.1", port=9999)

    mock_reader = AsyncMock()
    mock_reader.read.return_value = b"Name: HAProxy\nVersion: 2.8.5\n"
    mock_writer = make_mock_writer()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        assert await client.ping() is True

    # Simular fallo de conexión
    with patch("asyncio.open_connection", side_effect=OSError("Connection refused")):
        assert await client.ping() is False


@pytest.mark.asyncio
async def test_haproxy_timeout() -> None:
    """Verifica que un timeout levante HAProxyClientError."""
    client = HAProxySocketClient(host="127.0.0.1", port=9999, timeout=0.01)

    async def _slow_connection(*args: object, **kwargs: object) -> tuple[AsyncMock, MagicMock]:
        await asyncio.sleep(0.1)
        return AsyncMock(), make_mock_writer()

    with (
        patch("asyncio.open_connection", side_effect=_slow_connection),
        pytest.raises(HAProxyClientError, match="Timeout"),
    ):
        await client.send_command("show info")

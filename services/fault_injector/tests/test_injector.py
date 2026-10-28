"""Pruebas unitarias para el inyector de fallas F1 a F4, adaptadores Docker y CLI."""

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from services.fault_injector.src.cli import app, get_injector
from services.fault_injector.src.injector import (
    DockerClientProtocol,
    DockerFaultInjector,
    StandardDockerClientAdapter,
)
from services.fault_injector.src.models import (
    FaultInjectionError,
    FaultInjectorConfig,
    FaultRestoreError,
    FaultType,
)
from services.orchestrator.src.clock import MockClock


class MockDockerClient(DockerClientProtocol):
    """Doble de prueba para DockerClientProtocol sin depender del daemon de Docker."""

    def __init__(self) -> None:
        self.killed_containers: list[tuple[str, str]] = []
        self.started_containers: list[str] = []
        self.disconnected_networks: list[tuple[str, str]] = []
        self.connected_networks: list[tuple[str, str]] = []
        self.exec_commands: list[tuple[str, str | list[str]]] = []
        self.exec_responses: dict[str, tuple[int, bytes]] = {}
        self.should_fail_kill = False
        self.should_fail_start = False
        self.should_fail_connect = False
        self.should_fail_exec = False
        self.running_status: dict[str, bool] = {}

    def kill_container(self, container_id: str, signal: str = "SIGKILL") -> None:
        if self.should_fail_kill:
            raise RuntimeError(f"Error forzado al matar contenedor {container_id}")
        self.killed_containers.append((container_id, signal))
        self.running_status[container_id] = False

    def start_container(self, container_id: str) -> None:
        if self.should_fail_start:
            raise RuntimeError(f"Error forzado al arrancar contenedor {container_id}")
        self.started_containers.append(container_id)
        self.running_status[container_id] = True

    def disconnect_network(self, network_id: str, container_id: str) -> None:
        self.disconnected_networks.append((network_id, container_id))

    def connect_network(self, network_id: str, container_id: str) -> None:
        if self.should_fail_connect:
            raise RuntimeError(f"Error forzado al conectar red {network_id}")
        self.connected_networks.append((network_id, container_id))

    def exec_run(self, container_id: str, cmd: str | list[str]) -> tuple[int, bytes]:
        self.exec_commands.append((container_id, cmd))
        if self.should_fail_exec:
            return 1, b"RTNETLINK answers: Permission denied"
        cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
        if cmd_str in self.exec_responses:
            return self.exec_responses[cmd_str]
        return 0, b"OK"

    def is_container_running(self, container_id: str) -> bool:
        return self.running_status.get(container_id, False)


@pytest.fixture
def mock_clock() -> MockClock:
    return MockClock(start_ns=1_700_000_000_000_000_000)


@pytest.fixture
def mock_docker() -> MockDockerClient:
    return MockDockerClient()


@pytest.fixture
def injector(mock_docker: MockDockerClient, mock_clock: MockClock) -> DockerFaultInjector:
    config = FaultInjectorConfig(
        app_a_containers=["app-a-1", "app-a-2"],
        control_plane_network="test_control_plane",
        db_a_container="test_db_a",
        netem_target_container="app-a-1",
        netem_delay_ms=2000,
        netem_loss_pct=20.0,
        netem_interface="eth0",
    )
    return DockerFaultInjector(config=config, docker_client=mock_docker, clock=mock_clock)


def test_f1_inject_and_restore(
    injector: DockerFaultInjector,
    mock_docker: MockDockerClient,
    mock_clock: MockClock,
) -> None:
    """Verifica que F1 envía SIGKILL a todos los contenedores app-a y registra t_falla antes."""
    mock_clock.set_ns(1_700_000_000_123_456_789)
    result = injector.inject(FaultType.F1)

    assert result.fault == FaultType.F1
    assert result.t_fault_ns == 1_700_000_000_123_456_789
    assert result.success is True
    assert ("app-a-1", "SIGKILL") in mock_docker.killed_containers
    assert ("app-a-2", "SIGKILL") in mock_docker.killed_containers

    # Restaurar F1
    mock_clock.set_ns(1_700_000_000_999_000_000)
    restore_res = injector.restore(FaultType.F1)
    assert restore_res.fault == FaultType.F1
    assert restore_res.t_restore_ns == 1_700_000_000_999_000_000
    assert restore_res.success is True
    assert "app-a-1" in mock_docker.started_containers
    assert "app-a-2" in mock_docker.started_containers


def test_f1_restore_with_warning(
    injector: DockerFaultInjector,
    mock_docker: MockDockerClient,
) -> None:
    """Verifica que fallos de inicio parcial durante restore F1 se manejan con advertencia."""
    mock_docker.should_fail_start = True
    restore_res = injector.restore(FaultType.F1)
    assert restore_res.success is True
    assert restore_res.details["started_containers"] == []


def test_f1_inject_error_raises_fault_injection_error(
    injector: DockerFaultInjector,
    mock_docker: MockDockerClient,
) -> None:
    """Verifica manejo de excepción al fallar el comando de kill en Docker."""
    mock_docker.should_fail_kill = True
    with pytest.raises(FaultInjectionError) as exc_info:
        injector.inject(FaultType.F1)
    assert "Error al inyectar falla F1" in str(exc_info.value)


def test_f2_inject_and_restore(
    injector: DockerFaultInjector,
    mock_docker: MockDockerClient,
    mock_clock: MockClock,
) -> None:
    """Verifica que F2 desconecta los contenedores de la red del plano de control."""
    result = injector.inject(FaultType.F2)
    assert result.fault == FaultType.F2
    assert result.success is True
    assert ("test_control_plane", "app-a-1") in mock_docker.disconnected_networks
    assert ("test_control_plane", "app-a-2") in mock_docker.disconnected_networks

    # Restaurar F2
    restore_res = injector.restore(FaultType.F2)
    assert restore_res.fault == FaultType.F2
    assert restore_res.success is True
    assert ("test_control_plane", "app-a-1") in mock_docker.connected_networks
    assert ("test_control_plane", "app-a-2") in mock_docker.connected_networks


def test_f2_restore_with_warning(
    injector: DockerFaultInjector,
    mock_docker: MockDockerClient,
) -> None:
    """Verifica que fallos de conexión parcial durante restore F2 se manejan con advertencia."""
    mock_docker.should_fail_connect = True
    restore_res = injector.restore(FaultType.F2)
    assert restore_res.success is True
    assert restore_res.details["reconnected_containers"] == []


def test_f3_inject_and_restore(
    injector: DockerFaultInjector,
    mock_docker: MockDockerClient,
    mock_clock: MockClock,
) -> None:
    """Verifica que F3 envía SIGKILL a db-a y lo restaura arrancándolo."""
    result = injector.inject(FaultType.F3)
    assert result.fault == FaultType.F3
    assert result.success is True
    assert ("test_db_a", "SIGKILL") in mock_docker.killed_containers

    restore_res = injector.restore(FaultType.F3)
    assert restore_res.fault == FaultType.F3
    assert restore_res.success is True
    assert "test_db_a" in mock_docker.started_containers


def test_f3_restore_with_warning(
    injector: DockerFaultInjector,
    mock_docker: MockDockerClient,
) -> None:
    """Verifica que fallos de arranque de db-a se manejan con advertencia."""
    mock_docker.should_fail_start = True
    restore_res = injector.restore(FaultType.F3)
    assert restore_res.success is True


def test_f4_inject_and_restore(
    injector: DockerFaultInjector,
    mock_docker: MockDockerClient,
) -> None:
    """Verifica que F4 invoca tc netem con los parámetros de retardo y pérdida esperados."""
    result = injector.inject(FaultType.F4)
    assert result.fault == FaultType.F4
    assert result.success is True

    # Verificar que el comando tc qdisc add dev eth0 root netem delay 2000ms loss 20.0% fue ejecutado
    assert len(mock_docker.exec_commands) == 1
    target, cmd = mock_docker.exec_commands[0]
    assert target == "app-a-1"
    assert "tc qdisc add dev eth0 root netem delay 2000ms loss 20.0%" in cmd

    # Restaurar F4
    restore_res = injector.restore(FaultType.F4)
    assert restore_res.fault == FaultType.F4
    assert restore_res.success is True
    assert len(mock_docker.exec_commands) == 2
    del_target, del_cmd = mock_docker.exec_commands[1]
    assert del_target == "app-a-1"
    assert "tc qdisc del dev eth0 root netem" in del_cmd


def test_f4_inject_file_exists_fallback(
    injector: DockerFaultInjector,
    mock_docker: MockDockerClient,
) -> None:
    """Verifica que si la regla tc ya existía, se reintenta con tc qdisc change."""
    add_cmd = "tc qdisc add dev eth0 root netem delay 2000ms loss 20.0%"
    mock_docker.exec_responses[add_cmd] = (2, b"RTNETLINK answers: File exists")
    change_cmd = "tc qdisc change dev eth0 root netem delay 2000ms loss 20.0%"
    mock_docker.exec_responses[change_cmd] = (0, b"Updated")

    result = injector.inject(FaultType.F4)
    assert result.success is True
    assert len(mock_docker.exec_commands) == 2


def test_f4_inject_failure_raises_error(
    injector: DockerFaultInjector,
    mock_docker: MockDockerClient,
) -> None:
    """Verifica que un error no recuperable en tc netem genera FaultInjectionError."""
    mock_docker.should_fail_exec = True
    with pytest.raises(FaultInjectionError) as exc_info:
        injector.inject(FaultType.F4)
    assert "Fallo al ejecutar tc netem" in str(exc_info.value)


def test_inject_invalid_fault_raises_error(injector: DockerFaultInjector) -> None:
    """Verifica que una falla no contemplada lanza FaultInjectionError."""
    with pytest.raises(FaultInjectionError):
        injector.inject("UNKNOWN")  # type: ignore[arg-type]


def test_restore_invalid_fault_raises_error(injector: DockerFaultInjector) -> None:
    """Verifica que una falla no contemplada lanza FaultRestoreError."""
    with pytest.raises(FaultRestoreError):
        injector.restore("UNKNOWN")  # type: ignore[arg-type]


def test_standard_docker_adapter() -> None:
    """Verifica el adaptador StandardDockerClientAdapter contra un mock de docker-py."""
    mock_docker_module = MagicMock()
    mock_container = MagicMock()
    mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"ok")
    mock_container.status = "running"
    mock_network = MagicMock()

    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container
    mock_client.networks.get.return_value = mock_network
    mock_docker_module.from_env.return_value = mock_client
    mock_docker_module.DockerClient.return_value = mock_client

    with patch.dict("sys.modules", {"docker": mock_docker_module}):
        adapter = StandardDockerClientAdapter()
        adapter.kill_container("c1", signal="SIGKILL")
        mock_container.kill.assert_called_with(signal="SIGKILL")

        adapter.start_container("c1")
        mock_container.start.assert_called_once()

        adapter.disconnect_network("net1", "c1")
        mock_network.disconnect.assert_called_with("c1")

        adapter.connect_network("net1", "c1")
        mock_network.connect.assert_called_with("c1")

        # Probar connect_network con error 'already exists' (idempotencia)
        mock_network.connect.side_effect = RuntimeError("Endpoint already exists in network")
        adapter.connect_network("net1", "c1")  # No debe lanzar excepción

        # Probar connect_network con error real
        mock_network.connect.side_effect = RuntimeError("Network not found")
        with pytest.raises(RuntimeError):
            adapter.connect_network("net1", "c1")

        # Probar exec_run
        code, out = adapter.exec_run("c1", "echo 1")
        assert code == 0
        assert out == b"ok"

        # Probar is_container_running
        assert adapter.is_container_running("c1") is True

        # Probar base_url custom
        _ = StandardDockerClientAdapter(base_url="tcp://localhost:2375")
        mock_docker_module.DockerClient.assert_called_with(base_url="tcp://localhost:2375")


def test_cli_inject_and_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica la ejecución de los comandos Typer inject, restore y restore_all."""
    mock_doc = MockDockerClient()
    mock_clk = MockClock(start_ns=1_000_000_000)
    fake_injector = DockerFaultInjector(docker_client=mock_doc, clock=mock_clk)

    # Inyectar fake_injector en el módulo cli
    monkeypatch.setattr("services.fault_injector.src.cli.get_injector", lambda: fake_injector)

    runner = CliRunner()

    # Probar CLI inject F1 sin json
    res1 = runner.invoke(app, ["inject", "--fault", "F1"])
    assert res1.exit_code == 0
    assert "Falla F1 inyectada con éxito" in res1.stdout

    # Probar CLI inject F2 con json
    res2 = runner.invoke(app, ["inject", "-f", "F2", "--json"])
    assert res2.exit_code == 0
    assert '"fault": "F2"' in res2.stdout
    assert '"success": true' in res2.stdout

    # Probar CLI restore F1
    res3 = runner.invoke(app, ["restore", "--fault", "F1"])
    assert res3.exit_code == 0
    assert "Falla F1 restaurada con éxito" in res3.stdout

    # Probar CLI restore F2 con json
    res3_json = runner.invoke(app, ["restore", "--fault", "F2", "--json"])
    assert res3_json.exit_code == 0
    assert '"fault": "F2"' in res3_json.stdout

    # Probar CLI restore_all con json
    res4 = runner.invoke(app, ["restore-all", "--json"])
    assert res4.exit_code == 0
    assert '"success": true' in res4.stdout

    # Probar CLI restore_all sin json
    res5 = runner.invoke(app, ["restore-all"])
    assert res5.exit_code == 0
    assert "Restaurado F1" in res5.stdout


def test_cli_error_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica el código de salida 1 cuando ocurre un error en CLI."""
    mock_doc = MockDockerClient()
    mock_doc.should_fail_kill = True
    fake_injector = DockerFaultInjector(docker_client=mock_doc)

    monkeypatch.setattr("services.fault_injector.src.cli.get_injector", lambda: fake_injector)

    runner = CliRunner()
    res = runner.invoke(app, ["inject", "--fault", "F1", "--json"])
    assert res.exit_code == 1
    assert '"success": false' in res.stdout

    res_txt = runner.invoke(app, ["inject", "--fault", "F1"])
    assert res_txt.exit_code == 1
    assert "Error al inyectar falla F1" in res_txt.stdout


def test_cli_restore_error_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica el código de salida 1 cuando ocurre un error en restore CLI."""
    mock_doc = MockDockerClient()
    fake_injector = DockerFaultInjector(docker_client=mock_doc)
    monkeypatch.setattr(
        fake_injector, "restore", MagicMock(side_effect=RuntimeError("Fallo restore"))
    )
    monkeypatch.setattr("services.fault_injector.src.cli.get_injector", lambda: fake_injector)

    runner = CliRunner()
    res_json = runner.invoke(app, ["restore", "--fault", "F1", "--json"])
    assert res_json.exit_code == 1
    assert '"success": false' in res_json.stdout

    res_txt = runner.invoke(app, ["restore", "--fault", "F1"])
    assert res_txt.exit_code == 1
    assert "Error al restaurar falla F1" in res_txt.stdout


def test_cli_restore_all_with_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que restore_all sale con código 1 si alguna restauración falla."""
    mock_doc = MockDockerClient()
    fake_injector = DockerFaultInjector(docker_client=mock_doc)
    monkeypatch.setattr(
        fake_injector, "restore", MagicMock(side_effect=RuntimeError("Fallo general"))
    )
    monkeypatch.setattr("services.fault_injector.src.cli.get_injector", lambda: fake_injector)

    runner = CliRunner()
    res = runner.invoke(app, ["restore-all"])
    assert res.exit_code == 1
    assert "Falló F1" in res.stdout


def test_get_injector_default() -> None:
    """Verifica la función get_injector."""
    with patch("services.fault_injector.src.injector.StandardDockerClientAdapter"):
        injector = get_injector()
        assert isinstance(injector, DockerFaultInjector)

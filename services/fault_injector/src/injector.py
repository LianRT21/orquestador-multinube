"""Lógica e implementación del inyector de fallas F1 a F4 para Docker."""

from typing import Protocol, runtime_checkable

import structlog

from services.fault_injector.src.models import (
    FaultInjectionError,
    FaultInjectorConfig,
    FaultInjectorError,
    FaultRestoreError,
    FaultResult,
    FaultType,
    RestoreResult,
)
from services.orchestrator.src.clock import ClockProtocol, SystemClock

logger = structlog.get_logger("fault_injector")


@runtime_checkable
class DockerClientProtocol(Protocol):
    """Protocolo abstracto para interactuar con el daemon de Docker."""

    def kill_container(self, container_id: str, signal: str = "SIGKILL") -> None:
        """Envía una señal de terminación a un contenedor."""
        ...

    def start_container(self, container_id: str) -> None:
        """Inicia un contenedor detenido."""
        ...

    def disconnect_network(self, network_id: str, container_id: str) -> None:
        """Desconecta un contenedor de una red Docker."""
        ...

    def connect_network(self, network_id: str, container_id: str) -> None:
        """Conecta un contenedor a una red Docker."""
        ...

    def exec_run(self, container_id: str, cmd: str | list[str]) -> tuple[int, bytes]:
        """Ejecuta un comando dentro de un contenedor en ejecución."""
        ...

    def is_container_running(self, container_id: str) -> bool:
        """Verifica si un contenedor se encuentra en estado de ejecución."""
        ...


class StandardDockerClientAdapter(DockerClientProtocol):
    """Adaptador estándar sobre la librería oficial docker-py."""

    def __init__(self, base_url: str | None = None) -> None:
        import docker

        if base_url:
            self._client = docker.DockerClient(base_url=base_url)
        else:
            self._client = docker.from_env()

    def kill_container(self, container_id: str, signal: str = "SIGKILL") -> None:
        container = self._client.containers.get(container_id)
        container.kill(signal=signal)

    def start_container(self, container_id: str) -> None:
        container = self._client.containers.get(container_id)
        container.start()

    def disconnect_network(self, network_id: str, container_id: str) -> None:
        network = self._client.networks.get(network_id)
        network.disconnect(container_id)

    def connect_network(self, network_id: str, container_id: str) -> None:
        network = self._client.networks.get(network_id)
        try:
            network.connect(container_id)
        except Exception as exc:
            # Si ya está conectado, ignorar error de conexión previa
            if "already exists" in str(exc).lower() or "endpoint" in str(exc).lower():
                return
            raise

    def exec_run(self, container_id: str, cmd: str | list[str]) -> tuple[int, bytes]:
        container = self._client.containers.get(container_id)
        result = container.exec_run(cmd)
        exit_code = int(result.exit_code) if result.exit_code is not None else 1
        output = bytes(result.output) if result.output is not None else b""
        return exit_code, output

    def is_container_running(self, container_id: str) -> bool:
        try:
            container = self._client.containers.get(container_id)
            return bool(container.status == "running")
        except Exception:
            return False


@runtime_checkable
class FaultInjectorProtocol(Protocol):
    """Protocolo para inyección y restauración de perturbaciones."""

    def inject(self, fault: FaultType) -> FaultResult:
        """Inyecta una falla registrando la marca de tiempo exacta t_falla."""
        ...

    def restore(self, fault: FaultType) -> RestoreResult:
        """Restaura el estado original previo a la inyección de la falla."""
        ...


class DockerFaultInjector(FaultInjectorProtocol):
    """Inyector de fallas para entornos Docker con soporte para F1, F2, F3 y F4."""

    def __init__(
        self,
        config: FaultInjectorConfig | None = None,
        docker_client: DockerClientProtocol | None = None,
        clock: ClockProtocol | None = None,
    ) -> None:
        self.config = config or FaultInjectorConfig()
        self._docker = docker_client or StandardDockerClientAdapter(self.config.docker_base_url)
        self._clock = clock or SystemClock()

    def inject(self, fault: FaultType) -> FaultResult:
        """Inyecta la falla indicada registrando t_falla en nanosegundos antes de la acción."""
        t_fault_ns = self._clock.now_ns()
        fault_val = getattr(fault, "value", str(fault))
        logger.info(
            "fault_injection_started",
            fault=fault_val,
            t_fault_ns=t_fault_ns,
        )

        try:
            if fault == FaultType.F1:
                return self._inject_f1(t_fault_ns)
            elif fault == FaultType.F2:
                return self._inject_f2(t_fault_ns)
            elif fault == FaultType.F3:
                return self._inject_f3(t_fault_ns)
            elif fault == FaultType.F4:
                return self._inject_f4(t_fault_ns)
            else:
                raise FaultInjectionError(f"Tipo de falla no soportado: {fault_val}")
        except FaultInjectorError:
            raise
        except Exception as exc:
            logger.error("fault_injection_failed", fault=fault_val, error=str(exc))
            raise FaultInjectionError(f"Error al inyectar falla {fault_val}: {exc}") from exc

    def restore(self, fault: FaultType) -> RestoreResult:
        """Restaura el entorno para el tipo de falla especificado."""
        t_restore_ns = self._clock.now_ns()
        fault_val = getattr(fault, "value", str(fault))
        logger.info(
            "fault_restore_started",
            fault=fault_val,
            t_restore_ns=t_restore_ns,
        )

        try:
            if fault == FaultType.F1:
                return self._restore_f1(t_restore_ns)
            elif fault == FaultType.F2:
                return self._restore_f2(t_restore_ns)
            elif fault == FaultType.F3:
                return self._restore_f3(t_restore_ns)
            elif fault == FaultType.F4:
                return self._restore_f4(t_restore_ns)
            else:
                raise FaultRestoreError(
                    f"Tipo de falla no soportado para restauración: {fault_val}"
                )
        except FaultInjectorError:
            raise
        except Exception as exc:
            logger.error("fault_restore_failed", fault=fault_val, error=str(exc))
            raise FaultRestoreError(f"Error al restaurar falla {fault_val}: {exc}") from exc

    def _inject_f1(self, t_fault_ns: int) -> FaultResult:
        """F1: SIGKILL a todos los contenedores app de N1."""
        killed: list[str] = []
        for container_name in self.config.app_a_containers:
            self._docker.kill_container(container_name, signal="SIGKILL")
            killed.append(container_name)

        logger.info("f1_injected", killed_containers=killed, t_fault_ns=t_fault_ns)
        return FaultResult(
            fault=FaultType.F1,
            t_fault_ns=t_fault_ns,
            success=True,
            details={"killed_containers": killed},
        )

    def _restore_f1(self, t_restore_ns: int) -> RestoreResult:
        """Restaura F1: inicia los contenedores app de N1."""
        started: list[str] = []
        for container_name in self.config.app_a_containers:
            try:
                self._docker.start_container(container_name)
                started.append(container_name)
            except Exception as exc:
                logger.warning("f1_restore_start_warning", container=container_name, error=str(exc))

        logger.info("f1_restored", started_containers=started, t_restore_ns=t_restore_ns)
        return RestoreResult(
            fault=FaultType.F1,
            t_restore_ns=t_restore_ns,
            success=True,
            details={"started_containers": started},
        )

    def _inject_f2(self, t_fault_ns: int) -> FaultResult:
        """F2: Desconecta los contenedores app de N1 de la red del plano de control."""
        disconnected: list[str] = []
        for container_name in self.config.app_a_containers:
            self._docker.disconnect_network(self.config.control_plane_network, container_name)
            disconnected.append(container_name)

        logger.info(
            "f2_injected",
            network=self.config.control_plane_network,
            disconnected=disconnected,
            t_fault_ns=t_fault_ns,
        )
        return FaultResult(
            fault=FaultType.F2,
            t_fault_ns=t_fault_ns,
            success=True,
            details={
                "network": self.config.control_plane_network,
                "disconnected_containers": disconnected,
            },
        )

    def _restore_f2(self, t_restore_ns: int) -> RestoreResult:
        """Restaura F2: reconecta los contenedores app de N1 a la red del plano de control."""
        reconnected: list[str] = []
        for container_name in self.config.app_a_containers:
            try:
                self._docker.connect_network(self.config.control_plane_network, container_name)
                reconnected.append(container_name)
            except Exception as exc:
                logger.warning(
                    "f2_restore_connect_warning", container=container_name, error=str(exc)
                )

        logger.info(
            "f2_restored",
            network=self.config.control_plane_network,
            reconnected=reconnected,
            t_restore_ns=t_restore_ns,
        )
        return RestoreResult(
            fault=FaultType.F2,
            t_restore_ns=t_restore_ns,
            success=True,
            details={
                "network": self.config.control_plane_network,
                "reconnected_containers": reconnected,
            },
        )

    def _inject_f3(self, t_fault_ns: int) -> FaultResult:
        """F3: SIGKILL al contenedor db-a primario."""
        container_name = self.config.db_a_container
        self._docker.kill_container(container_name, signal="SIGKILL")

        logger.info("f3_injected", killed_container=container_name, t_fault_ns=t_fault_ns)
        return FaultResult(
            fault=FaultType.F3,
            t_fault_ns=t_fault_ns,
            success=True,
            details={"killed_container": container_name},
        )

    def _restore_f3(self, t_restore_ns: int) -> RestoreResult:
        """Restaura F3: inicia el contenedor db-a primario."""
        container_name = self.config.db_a_container
        try:
            self._docker.start_container(container_name)
        except Exception as exc:
            logger.warning("f3_restore_start_warning", container=container_name, error=str(exc))

        logger.info("f3_restored", started_container=container_name, t_restore_ns=t_restore_ns)
        return RestoreResult(
            fault=FaultType.F3,
            t_restore_ns=t_restore_ns,
            success=True,
            details={"started_container": container_name},
        )

    def _inject_f4(self, t_fault_ns: int) -> FaultResult:
        """F4: Aplica tc netem (delay 2000ms loss 20%) en la interfaz de app-a."""
        target = self.config.netem_target_container
        interface = self.config.netem_interface
        delay = self.config.netem_delay_ms
        loss = self.config.netem_loss_pct

        # Comando para configurar emulación de red mediante traffic control
        cmd = f"tc qdisc add dev {interface} root netem delay {delay}ms loss {loss:.1f}%"
        exit_code, output = self._docker.exec_run(target, cmd)

        if exit_code != 0:
            # Si la regla ya existe (File exists), intentamos reemplazarla
            output_str = output.decode("utf-8", errors="replace")
            if "File exists" in output_str:
                cmd_replace = (
                    f"tc qdisc change dev {interface} root netem delay {delay}ms loss {loss:.1f}%"
                )
                exit_code, output = self._docker.exec_run(target, cmd_replace)

        if exit_code != 0:
            err_msg = output.decode("utf-8", errors="replace")
            logger.error("f4_tc_netem_failed", target=target, code=exit_code, output=err_msg)
            raise FaultInjectionError(f"Fallo al ejecutar tc netem en {target}: {err_msg}")

        logger.info(
            "f4_injected",
            target=target,
            interface=interface,
            delay_ms=delay,
            loss_pct=loss,
            t_fault_ns=t_fault_ns,
        )
        return FaultResult(
            fault=FaultType.F4,
            t_fault_ns=t_fault_ns,
            success=True,
            details={
                "target_container": target,
                "interface": interface,
                "delay_ms": delay,
                "loss_pct": loss,
            },
        )

    def _restore_f4(self, t_restore_ns: int) -> RestoreResult:
        """Restaura F4: elimina la regla tc netem de la interfaz de app-a."""
        target = self.config.netem_target_container
        interface = self.config.netem_interface

        cmd = f"tc qdisc del dev {interface} root netem"
        exit_code, output = self._docker.exec_run(target, cmd)

        # Si exit_code != 0 porque no existía la regla, es idempotente
        output_str = output.decode("utf-8", errors="replace")
        logger.info(
            "f4_restored",
            target=target,
            interface=interface,
            exit_code=exit_code,
            output=output_str,
            t_restore_ns=t_restore_ns,
        )
        return RestoreResult(
            fault=FaultType.F4,
            t_restore_ns=t_restore_ns,
            success=True,
            details={
                "target_container": target,
                "interface": interface,
                "output": output_str,
            },
        )

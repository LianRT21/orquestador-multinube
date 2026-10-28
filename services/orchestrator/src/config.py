"""Configuración tipada del orquestador mediante Pydantic Settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OrchestratorSettings(BaseSettings):
    """Parámetros de configuración del motor de conmutación por error."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Parámetros de sondas y detección
    PROBE_INTERVAL_S: float = Field(
        default=1.0, description="Intervalo entre rondas de sondas (segundos)"
    )
    PROBE_TIMEOUT_S: float = Field(
        default=1.0, description="Timeout máximo por sonda HTTP (segundos)"
    )
    FAILURE_THRESHOLD: int = Field(
        default=3, description="Umbral de fallos consecutivos para conmutar"
    )
    DEGRADED_LATENCY_MS: float = Field(
        default=1500.0, description="Latencia límite para degradación parcial (F4)"
    )

    # Endpoints de sondeo y proxy
    N1_HEALTH_URLS: list[str] = Field(
        default=["http://app-a:8000/health"],
        description="URLs de salud de todas las instancias de Nube 1",
    )
    N2_HEALTH_URLS: list[str] = Field(
        default=["http://app-b:8000/health"],
        description="URLs de salud de las instancias de Nube 2",
    )
    PROXY_HEALTH_URL: str = Field(
        default="http://haproxy:80/health",
        description="Endpoint público de salud a través del proxy L7",
    )
    PROXY_ORDERS_URL: str = Field(
        default="http://haproxy:80/orders",
        description="Endpoint de pedidos para verificación sintética post-failover",
    )

    # HAProxy Runtime API
    HAPROXY_HOST: str = Field(default="haproxy", description="Host o IP del proxy HAProxy")
    HAPROXY_PORT: int = Field(default=9999, description="Puerto TCP de la Runtime API de HAProxy")
    HAPROXY_BACKEND: str = Field(default="app_back", description="Nombre del backend en HAProxy")
    HAPROXY_SERVER_A: str = Field(default="app-a", description="Nombre del servidor N1 en HAProxy")
    HAPROXY_SERVER_B: str = Field(default="app-b", description="Nombre del servidor N2 en HAProxy")

    # Base de datos N2 (para promoción)
    DB_B_HOST: str = Field(default="db-b", description="Host de PostgreSQL réplica en N2")
    DB_B_PORT: int = Field(default=5432, description="Puerto de PostgreSQL réplica")
    POSTGRES_USER: str = Field(
        default="postgres", description="Usuario administrativo de base de datos"
    )
    POSTGRES_PASSWORD: str = Field(
        default="postgres_dev_pass", description="Contraseña de base de datos"
    )
    POSTGRES_DB: str = Field(
        default="orders_db", description="Nombre de la base de datos de órdenes"
    )

    # Persistencia de eventos y API
    EVENTS_LOG_PATH: str = Field(
        default="data/raw/events.jsonl", description="Archivo de log de eventos"
    )
    ORCHESTRATOR_HOST: str = Field(
        default="0.0.0.0", description="Dirección de escucha de la API admin"
    )
    ORCHESTRATOR_PORT: int = Field(default=8080, description="Puerto de la API de administración")


orchestrator_settings = OrchestratorSettings()

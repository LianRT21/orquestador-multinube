"""Configuración tipada de la aplicación de referencia mediante Pydantic Settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Parámetros de configuración del servicio."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    CLOUD_ID: str = Field(
        default="cloud_a", description="Identificador de la nube (cloud_a o cloud_b)"
    )
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres_dev_pass@localhost:5432/orders_db",
        description="Cadena de conexión asíncrona a PostgreSQL",
    )
    APP_PORT: int = Field(default=8000, description="Puerto de escucha de la aplicación")
    APP_HOST: str = Field(default="0.0.0.0", description="Dirección de escucha")

    DB_TIMEOUT_SECONDS: float = Field(
        default=1.0, description="Timeout máximo para consultas de health check"
    )
    DB_POOL_SIZE: int = Field(default=20, description="Tamaño del pool de conexiones")
    DB_MAX_OVERFLOW: int = Field(default=10, description="Sobrecupo máximo del pool")
    ROLE_CACHE_TTL_SECONDS: float = Field(
        default=1.0,
        description="Tiempo de vida de la caché del rol de base de datos (segundos)",
    )


settings = Settings()

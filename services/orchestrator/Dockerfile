# ==============================================================================
# Multi-stage Dockerfile for Failover Orchestrator
# ==============================================================================

# Etapa 1: Builder
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY services/orchestrator/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Etapa 2: Runtime final
FROM python:3.12-slim-bookworm AS runner

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 10002 orchuser

COPY --from=builder /root/.local /home/orchuser/.local
COPY services /app/services

# Crear carpeta de datos con permisos
RUN mkdir -p /app/data/raw && chown -R orchuser:orchuser /app/data

ENV PATH=/home/orchuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

USER orchuser

EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=2s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:8080/health || exit 1

CMD ["uvicorn", "services.orchestrator.src.main:app", "--host", "0.0.0.0", "--port", "8080"]

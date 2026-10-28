# ==============================================================================
# Multi-stage Dockerfile for Reference Application
# ==============================================================================

# Etapa 1: Builder
FROM python:3.12-slim-bookworm AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY services/reference_app/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Etapa 2: Runtime final
FROM python:3.12-slim-bookworm AS runner

WORKDIR /app

# Instalar librerías de runtime necesarias (libpq) y curl para healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Crear usuario sin privilegios
RUN useradd -m -u 10001 appuser

# Copiar dependencias de usuario desde la etapa builder
COPY --from=builder /root/.local /home/appuser/.local

# Copiar código fuente
COPY services /app/services

ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=2s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "services.reference_app.src.main:app", "--host", "0.0.0.0", "--port", "8000"]

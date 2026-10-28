#!/bin/bash
set -e

PRIMARY_HOST="${PRIMARY_HOST:-toxiproxy}"
PRIMARY_PORT="${PRIMARY_PORT:-5434}"
REPLICATION_USER="${REPLICATION_USER:-replicator}"
REPLICATION_PASSWORD="${REPLICATION_PASSWORD:-replicator_dev_pass}"
REPLICATION_SLOT="${REPLICATION_SLOT:-standby_slot}"

echo "[REPLICA] Iniciando punto de entrada para réplica db-b..."

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "[REPLICA] PGDATA vacío. Esperando a que el primario esté disponible en ${PRIMARY_HOST}:${PRIMARY_PORT}..."
    until PGPASSWORD="$REPLICATION_PASSWORD" pg_isready -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" -U "$REPLICATION_USER"; do
        echo "[REPLICA] Esperando disponibilidad de base primaria..."
        sleep 2
    done

    echo "[REPLICA] Ejecutando pg_basebackup desde ${PRIMARY_HOST}:${PRIMARY_PORT}..."
    rm -rf "$PGDATA"/*
    until PGPASSWORD="$REPLICATION_PASSWORD" pg_basebackup \
        -h "$PRIMARY_HOST" \
        -p "$PRIMARY_PORT" \
        -U "$REPLICATION_USER" \
        -D "$PGDATA" \
        -Fp \
        -Xs \
        -P \
        -R \
        -S "$REPLICATION_SLOT"; do
        echo "[REPLICA] Falló pg_basebackup (posible inicialización en curso). Reintentando en 3s..."
        sleep 3
    done

    echo "[REPLICA] pg_basebackup completado. standby.signal configurado."
    chmod 700 "$PGDATA"
fi

echo "[REPLICA] Arrancando servidor PostgreSQL en modo réplica..."
exec docker-entrypoint.sh postgres \
    -c hot_standby=on \
    -c listen_addresses='*'

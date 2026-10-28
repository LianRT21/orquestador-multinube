#!/bin/bash
set -e

echo "[INIT] Inicializando base de datos primaria (db-a)..."

REPLICATION_USER="${REPLICATION_USER:-replicator}"
REPLICATION_PASSWORD="${REPLICATION_PASSWORD:-replicator_dev_pass}"
REPLICATION_SLOT="${REPLICATION_SLOT:-standby_slot}"
APP_DB="${POSTGRES_DB:-orders_db}"

# Configurar pg_hba.conf para permitir replicación y conexiones externas
echo "host replication ${REPLICATION_USER} 0.0.0.0/0 md5" >> "$PGDATA/pg_hba.conf"
echo "host all all 0.0.0.0/0 md5" >> "$PGDATA/pg_hba.conf"

# Crear usuario de replicación
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER ${REPLICATION_USER} WITH REPLICATION ENCRYPTED PASSWORD '${REPLICATION_PASSWORD}';
    SELECT pg_create_physical_replication_slot('${REPLICATION_SLOT}');
EOSQL

# Crear tabla orders en la base de datos de la aplicación
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$APP_DB" <<-EOSQL
    CREATE TABLE IF NOT EXISTS orders (
        order_id UUID PRIMARY KEY,
        customer_id INT NOT NULL,
        amount NUMERIC(12, 2) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'COMPLETED',
        seq BIGSERIAL,
        committed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
    );

    CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
    CREATE INDEX IF NOT EXISTS idx_orders_seq ON orders(seq);
EOSQL

echo "[INIT] Primaria db-a inicializada exitosamente."

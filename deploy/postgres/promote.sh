#!/bin/bash
set -e

DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-orders_db}"

echo "[PROMOTE] Iniciando promoción de la réplica local..."
T_START=$(date +%s%N)

psql -v ON_ERROR_STOP=1 --username "$DB_USER" --dbname "$DB_NAME" <<-EOSQL
    SELECT pg_promote(wait => true, wait_seconds => 60);
EOSQL

T_END=$(date +%s%N)
DURATION_MS=$(( (T_END - T_START) / 1000000 ))

echo "[PROMOTE] Promoción completada exitosamente en ${DURATION_MS} ms."

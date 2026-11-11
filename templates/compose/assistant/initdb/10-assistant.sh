#!/bin/sh
# First start only: the assistant's own database, with its own user (n8n's database stays separate).
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE ROLE assistant LOGIN PASSWORD '${ASSISTANT_DB_PASSWORD}';
CREATE DATABASE assistant OWNER assistant;
EOSQL

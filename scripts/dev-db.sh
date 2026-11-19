#!/usr/bin/env bash
# Start a private PostgreSQL cluster for local development without Docker or sudo.
# Data lives in .local/pgdata (gitignored). Port 4822, bound to 127.0.0.1.
set -euo pipefail
cd "$(dirname "$0")/.."
PGBIN="${PGBIN:-$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)}"
PORT="${WALTRIX_PG_PORT:-4822}"
mkdir -p .local
if [ ! -d .local/pgdata ]; then
  "$PGBIN/initdb" -D .local/pgdata -U waltrix --auth=trust -E UTF8 --locale=C.UTF-8 >/dev/null
fi
if ! "$PGBIN/pg_ctl" -D .local/pgdata status >/dev/null 2>&1; then
  "$PGBIN/pg_ctl" -D .local/pgdata -l .local/pg.log -w start \
    -o "-p $PORT -k $PWD/.local -c listen_addresses=127.0.0.1 -c max_connections=200"
fi
for db in waltrix waltrix_test waltrix_e2e; do
  if ! psql -h 127.0.0.1 -p "$PORT" -U waltrix -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1; then
    psql -h 127.0.0.1 -p "$PORT" -U waltrix -d postgres -qc "CREATE DATABASE $db"
  fi
done
echo "PostgreSQL ready on 127.0.0.1:$PORT (databases: waltrix, waltrix_test, waltrix_e2e)"

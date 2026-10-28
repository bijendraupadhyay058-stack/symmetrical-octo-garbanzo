#!/usr/bin/env bash
# Runs the Supabase migrations and database tests against a throw-away local
# PostgreSQL 15+/16 cluster. Requires the PostgreSQL server binaries.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PGBIN="${PGBIN:-$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)}"
DATA="$(mktemp -d)"
PORT="${PGPORT_TEST:-54329}"
SOCK="$DATA"
cleanup() { "$PGBIN/pg_ctl" -D "$DATA/db" -m immediate stop >/dev/null 2>&1 || true; rm -rf "$DATA"; }
trap cleanup EXIT

RUNAS=""
if [ "$(id -u)" = "0" ]; then
  chown -R postgres "$DATA" 2>/dev/null || true
  RUNAS="runuser -u postgres --"
fi
$RUNAS "$PGBIN/initdb" -D "$DATA/db" -U postgres --auth=trust >/dev/null
$RUNAS "$PGBIN/pg_ctl" -D "$DATA/db" -o "-p $PORT -k $SOCK -c listen_addresses=''" -w start >/dev/null
PSQL=(psql -h "$SOCK" -p "$PORT" -U postgres -v ON_ERROR_STOP=1 -q -X)
"${PSQL[@]}" -c "create database fintax_test" >/dev/null
"${PSQL[@]}" -d fintax_test -f "$ROOT/supabase/tests/auth_stub.sql"
for f in "$ROOT"/supabase/migrations/*.sql; do
  echo "Applying $(basename "$f")"
  "${PSQL[@]}" -d fintax_test -f "$f"
done
echo "Running database tests"
"${PSQL[@]}" -d fintax_test -f "$ROOT/supabase/tests/db_test.sql"
echo "All database tests passed"

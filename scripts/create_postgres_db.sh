#!/usr/bin/env bash
# Create the PostgreSQL database and user for Diction Masters.
# Run once on a new machine or server:
#
#     bash scripts/create_postgres_db.sh
#
# It reads the name, user and password from .env, so there is nothing to
# type twice and no password ends up in your shell history.

set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "No .env file found. Copy .env.example to .env and fill it in first." >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a; source ./.env; set +a

: "${POSTGRES_DB:?POSTGRES_DB is not set in .env}"
: "${POSTGRES_USER:?POSTGRES_USER is not set in .env}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is not set in .env}"

echo "Creating database '$POSTGRES_DB' and user '$POSTGRES_USER'…"

sudo -u postgres psql --set ON_ERROR_STOP=on \
  --set dbname="$POSTGRES_DB" \
  --set dbuser="$POSTGRES_USER" \
  --set dbpass="$POSTGRES_PASSWORD" <<'SQL'
SELECT 'CREATE ROLE ' || quote_ident(:'dbuser') || ' LOGIN PASSWORD ' || quote_literal(:'dbpass')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'dbuser') \gexec

ALTER ROLE :"dbuser" WITH PASSWORD :'dbpass';
-- Django creates and drops a test database of its own when tests run on
-- PostgreSQL, and these keep migrations quick.
ALTER ROLE :"dbuser" SET client_encoding TO 'utf8';
ALTER ROLE :"dbuser" SET default_transaction_isolation TO 'read committed';
ALTER ROLE :"dbuser" SET timezone TO 'Africa/Lagos';

SELECT 'CREATE DATABASE ' || quote_ident(:'dbname') || ' OWNER ' || quote_ident(:'dbuser')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'dbname') \gexec

GRANT ALL PRIVILEGES ON DATABASE :"dbname" TO :"dbuser";
SQL

# The public schema belongs to the database, so grant inside it too.
sudo -u postgres psql --set ON_ERROR_STOP=on -d "$POSTGRES_DB" \
  -c "GRANT ALL ON SCHEMA public TO \"$POSTGRES_USER\";" \
  -c "ALTER SCHEMA public OWNER TO \"$POSTGRES_USER\";"

echo "Done. Now run:  DJANGO_DB=postgres python manage.py migrate"

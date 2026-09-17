#!/usr/bin/env bash
# Copy everything already in the SQLite database into PostgreSQL.
# Run it once, after scripts/create_postgres_db.sh:
#
#     bash scripts/move_data_to_postgres.sh
#
# Uploaded files are not touched: they already live on Cloudflare R2, and
# the database only holds links to them.

set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON=${PYTHON:-python}
STAMP=$(date +%Y%m%d-%H%M%S)
DUMP="backups/data-$STAMP.json"
mkdir -p backups

echo "1/3  Reading everything out of SQLite…"
DJANGO_DB=sqlite "$PYTHON" manage.py dumpdata \
  --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission \
  --exclude admin.logentry --exclude sessions.session \
  --indent 2 > "$DUMP"
echo "     saved $DUMP"

echo "2/3  Creating the tables in PostgreSQL…"
DJANGO_DB=postgres "$PYTHON" manage.py migrate --noinput

echo "3/3  Loading the data into PostgreSQL…"
DJANGO_DB=postgres "$PYTHON" manage.py loaddata "$DUMP"

echo "Done. Check it with:  DJANGO_DB=postgres $PYTHON manage.py shell -c \"from django.contrib.auth import get_user_model as u; print(u().objects.count(), 'users')\""

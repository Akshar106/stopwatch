#!/usr/bin/env bash
# Nightly logical backup of the Neon Postgres database (docs/05 §10.5, runbook RB-7).
#
#   pg_dump -Fc "$DATABASE_OWNER_URL"  ->  s3://$LAKE_BUCKET/backups/postgres/YYYY-MM-DD.dump
#
# Run by .github/workflows/nightly.yml with the stopwatch-backup-<env> role (it may read only the
# database_owner_url parameter and write only backups/postgres/*). The lake's lifecycle rule expires
# backups/ after 30 days, which is also the window promised in the privacy policy for deleted
# accounts to age out of backups. The maintenance job alarms if a night's dump is missing.
#
# Required env: DATABASE_OWNER_URL, LAKE_BUCKET.  Optional: BACKUP_DATE (default: today, UTC),
# AWS_REGION (default us-east-1). Needs pg_dump/pg_restore >= the server major version (17).
set -euo pipefail

: "${DATABASE_OWNER_URL:?set DATABASE_OWNER_URL (owner-role connection string)}"
: "${LAKE_BUCKET:?set LAKE_BUCKET (e.g. stopwatch-prod-lake)}"
region="${AWS_REGION:-us-east-1}"
backup_date="${BACKUP_DATE:-$(date -u +%Y-%m-%d)}"
[[ "$backup_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "BACKUP_DATE must be YYYY-MM-DD" >&2; exit 1; }
key="backups/postgres/${backup_date}.dump"

for bin in pg_dump pg_restore aws; do
  command -v "$bin" >/dev/null || { echo "backup_db: $bin is required" >&2; exit 1; }
done

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
dump="$workdir/stopwatch.dump"

echo "==> pg_dump ($(pg_dump --version | awk '{print $NF}')) -> $dump"
# The connection string is passed as an argument but never echoed; set -x must stay off here.
pg_dump --format=custom --compress=6 --no-password --lock-wait-timeout=30000 \
  --file="$dump" "$DATABASE_OWNER_URL"

# Cheap integrity check: the archive's table of contents must be readable.
pg_restore --list "$dump" >/dev/null
entries="$(pg_restore --list "$dump" | grep -cv '^;' || true)"
size_bytes="$(wc -c <"$dump" | tr -d ' ')"
sha256="$(python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$dump")"

echo "==> uploading s3://$LAKE_BUCKET/$key ($size_bytes bytes, $entries TOC entries)"
aws --region "$region" s3 cp "$dump" "s3://$LAKE_BUCKET/$key" \
  --only-show-errors \
  --content-type application/octet-stream \
  --metadata "sha256=$sha256,toc-entries=$entries"

echo "==> backup complete: s3://$LAKE_BUCKET/$key sha256=$sha256"

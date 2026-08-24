#!/bin/sh
# Migrate, then serve. Serving an unmigrated database would fail per-request instead
# of at startup, which is far harder to notice.
set -e

: "${VOICEOBS_DATABASE_URL:?VOICEOBS_DATABASE_URL is required}"

if [ "${VOICEOBS_SKIP_MIGRATE:-0}" = "1" ]; then
  echo "[vo] skipping migrations (VOICEOBS_SKIP_MIGRATE=1)"
else
  echo "[vo] alembic upgrade head"
  alembic upgrade head
fi

exec "$@"

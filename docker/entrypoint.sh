#!/bin/sh
# Wait for Postgres, migrate, optionally bootstrap the first owner, then serve.
# Serving an unmigrated database would fail per-request instead of at startup.
set -e

: "${VOICEOBS_DATABASE_URL:?VOICEOBS_DATABASE_URL is required}"

echo "[vo] waiting for database"
python - <<'PY'
import sys
import time

from sqlalchemy import create_engine, text

from voiceobs.config import get_config

url = get_config().database_url
for _ in range(60):
    try:
        engine = create_engine(url, future=True)
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        engine.dispose()
        print("[vo] database is up")
        break
    except Exception:
        time.sleep(2)
else:
    print("[vo] database not reachable after 120s", file=sys.stderr)
    sys.exit(1)
PY

if [ "${VOICEOBS_SKIP_MIGRATE:-0}" = "1" ]; then
  echo "[vo] skipping migrations (VOICEOBS_SKIP_MIGRATE=1)"
else
  echo "[vo] alembic upgrade head"
  alembic upgrade head
  # Safe to re-run: no-ops once any user exists. See voiceobs.auth bootstrap.
  if [ -n "${VOICEOBS_BOOTSTRAP_EMAIL:-}" ] && [ -n "${VOICEOBS_BOOTSTRAP_PASSWORD:-}" ]; then
    echo "[vo] bootstrap owner (no-op if users exist)"
    python -m voiceobs.auth bootstrap
  fi
fi

exec "$@"

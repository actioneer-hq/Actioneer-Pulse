# --- UI: built here so the runtime image carries no node ------------------- #
FROM node:22-alpine AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json* ./
RUN npm install
COPY ui ./
COPY src/voiceobs/api ../src/voiceobs/api
RUN npm run build

# --- API ------------------------------------------------------------------- #
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Source before install: the package is built from src/, so it has to be present.
COPY pyproject.toml ./
COPY src ./src
COPY --from=ui /src/voiceobs/api/static ./src/voiceobs/api/static
RUN pip install ".[pg,kafka]"

# Migrations ship with the image — the schema and the code that assumes it must
# never be able to drift apart across a deploy.
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "voiceobs.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

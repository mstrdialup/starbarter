FROM python:3.11-slim

WORKDIR /app

# Install only what we need
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir -e ".[web]"

# Data directory for SQLite persistence
RUN mkdir -p /data

ENV ST_DB_PATH=/data/spacetraders.db
ENV ST_WEB_PORT=8080

EXPOSE 8080

CMD ["st-web"]

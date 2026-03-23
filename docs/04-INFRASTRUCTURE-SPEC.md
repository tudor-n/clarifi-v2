# 04 — Infrastructure Specification

## Docker Compose (Development)

```yaml
# docker-compose.dev.yml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: clarifi
      POSTGRES_USER: clarifi
      POSTGRES_PASSWORD: clarifi_dev
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U clarifi"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: clarifi
      MINIO_ROOT_PASSWORD: clarifi_dev
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data

  minio-init:
    image: minio/mc:latest
    depends_on:
      minio:
        condition: service_started
    entrypoint: >
      /bin/sh -c "
      sleep 3;
      mc alias set local http://minio:9000 clarifi clarifi_dev;
      mc mb local/clarifi-uploads --ignore-existing;
      exit 0;
      "

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
      target: dev
    volumes:
      - ./backend/app:/app/app           # Hot reload
      - ./backend/tests:/app/tests
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql+asyncpg://clarifi:clarifi_dev@db:5432/clarifi
      REDIS_URL: redis://redis:6379/0
      SECRET_KEY: dev-secret-key-not-for-production
      STORAGE_BACKEND: s3
      S3_ENDPOINT_URL: http://minio:9000
      S3_ACCESS_KEY: clarifi
      S3_SECRET_KEY: clarifi_dev
      S3_BUCKET: clarifi-uploads
      ENVIRONMENT: development
      CORS_ORIGINS: '["http://localhost:5173"]'
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
      target: dev
    volumes:
      - ./backend/app:/app/app
    environment:
      DATABASE_URL: postgresql+asyncpg://clarifi:clarifi_dev@db:5432/clarifi
      REDIS_URL: redis://redis:6379/0
      SECRET_KEY: dev-secret-key-not-for-production
      STORAGE_BACKEND: s3
      S3_ENDPOINT_URL: http://minio:9000
      S3_ACCESS_KEY: clarifi
      S3_SECRET_KEY: clarifi_dev
      S3_BUCKET: clarifi-uploads
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }
    command: arq app.workers.celery_app.WorkerSettings

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
      target: dev
    volumes:
      - ./frontend/src:/app/src
    ports:
      - "5173:5173"
    command: npm run dev -- --host 0.0.0.0

volumes:
  pgdata:
  minio_data:
```

---

## Docker Compose (Production)

```yaml
# docker-compose.yml
services:
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks: [internal]

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: redis-server --requirepass ${REDIS_PASSWORD} --maxmemory 256mb --maxmemory-policy allkeys-lru
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
    networks: [internal]

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
      target: prod
    restart: unless-stopped
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
      SECRET_KEY: ${SECRET_KEY}
      ENVIRONMENT: production
      LLM_PROVIDER: ${LLM_PROVIDER:-gemini}
      LLM_API_KEY: ${LLM_API_KEY:-}
      STORAGE_BACKEND: ${STORAGE_BACKEND:-local}
      CORS_ORIGINS: ${CORS_ORIGINS}
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks: [internal]

  worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
      target: prod
    restart: unless-stopped
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
      SECRET_KEY: ${SECRET_KEY}
      LLM_PROVIDER: ${LLM_PROVIDER:-gemini}
      LLM_API_KEY: ${LLM_API_KEY:-}
      STORAGE_BACKEND: ${STORAGE_BACKEND:-local}
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }
    command: arq app.workers.celery_app.WorkerSettings
    deploy:
      replicas: 2
    networks: [internal]

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
      target: prod
      args:
        VITE_API_URL: ""
    restart: unless-stopped
    ports:
      - "${PORT:-80}:80"
    depends_on:
      backend: { condition: service_healthy }
    networks: [internal]

volumes:
  pgdata:

networks:
  internal:
    driver: bridge
```

---

## Backend Dockerfile (Multi-Stage)

```dockerfile
# backend/Dockerfile

# ── Base ─────────────────────────────────────
FROM python:3.12-slim AS base
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && rm -rf /var/lib/apt/lists/*

# ── Builder ──────────────────────────────────
FROM base AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir .

# ── Dev ──────────────────────────────────────
FROM base AS dev
COPY --from=builder /install /usr/local
COPY . .
RUN pip install --no-cache-dir .[dev]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── Prod ─────────────────────────────────────
FROM base AS prod
COPY --from=builder /install /usr/local
COPY app/ /app/app/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/
COPY pyproject.toml /app/
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8000/health || exit 1
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4"]
```

---

## CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  backend-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install ruff mypy
      - run: ruff check backend/
      - run: ruff format --check backend/
      - run: cd backend && mypy app/ --ignore-missing-imports

  backend-test:
    runs-on: ubuntu-latest
    needs: backend-lint
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: clarifi_test
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        ports: ["5433:5432"]
        options: --health-cmd pg_isready --health-interval 5s --health-timeout 3s --health-retries 5
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: cd backend && pip install .[dev]
      - run: cd backend && pytest tests/ -v --cov=app --cov-report=xml
        env:
          DATABASE_URL: postgresql+asyncpg://test:test@localhost:5433/clarifi_test
          REDIS_URL: redis://localhost:6379/0
          SECRET_KEY: test-secret
      - uses: codecov/codecov-action@v4
        with: { file: backend/coverage.xml }

  frontend-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: cd frontend && npm ci
      - run: cd frontend && npm run typecheck
      - run: cd frontend && npm run lint

  frontend-build:
    runs-on: ubuntu-latest
    needs: frontend-lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: cd frontend && npm ci
      - run: cd frontend && npm run build

  docker-build:
    runs-on: ubuntu-latest
    needs: [backend-test, frontend-build]
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          context: ./backend
          push: true
          tags: ghcr.io/${{ github.repository }}/backend:${{ github.sha }}
          target: prod
      - uses: docker/build-push-action@v5
        with:
          context: ./frontend
          push: true
          tags: ghcr.io/${{ github.repository }}/frontend:${{ github.sha }}
          target: prod
```

---

## Observability

### Structured Logging (structlog)

```python
# app/core/logging.py
import structlog

def setup_logging():
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer() if settings.is_production else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
```

### Health Check Endpoint

```python
@app.get("/health")
async def health():
    checks = {}
    status_code = 200

    # DB check
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception:
        checks["db"] = "error"
        status_code = 503

    # Redis check
    try:
        redis = aioredis.from_url(settings.redis_url)
        await redis.ping()
        checks["redis"] = "ok"
        await redis.close()
    except Exception:
        checks["redis"] = "error"
        status_code = 503

    # Worker check (are any workers alive?)
    try:
        info = await arq_redis.info()
        checks["workers"] = "ok" if info else "warning"
    except Exception:
        checks["workers"] = "unknown"

    overall = "ok" if status_code == 200 else "degraded"
    return JSONResponse(status_code=status_code, content={"status": overall, **checks})
```

---

## Makefile

```makefile
.PHONY: dev dev-down migrate test lint

# Start full dev environment
dev:
	docker compose -f docker-compose.dev.yml up --build

dev-down:
	docker compose -f docker-compose.dev.yml down -v

# Database
migrate:
	cd backend && alembic upgrade head

migrate-new:
	cd backend && alembic revision --autogenerate -m "$(MSG)"

# Testing
test-backend:
	cd backend && pytest tests/ -v --cov=app

test-frontend:
	cd frontend && npm run typecheck && npm run lint

test: test-backend test-frontend

# Linting
lint-backend:
	cd backend && ruff check . && ruff format --check .

lint-frontend:
	cd frontend && npm run lint

lint: lint-backend lint-frontend

# Production build
build:
	docker compose build

deploy:
	docker compose up -d
```

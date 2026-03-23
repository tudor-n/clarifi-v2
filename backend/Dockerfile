FROM python:3.12-slim AS base
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && rm -rf /var/lib/apt/lists/*

FROM base AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir .

FROM base AS dev
COPY --from=builder /install /usr/local
COPY . .
RUN pip install --no-cache-dir .[dev]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

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
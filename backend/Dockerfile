FROM python:3.12-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
RUN pip install --upgrade pip && pip install -e ".[dev]" --target /app/deps

FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=builder /app/deps /app/deps
ENV PYTHONPATH=/app/deps
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .
RUN useradd -m -u 1001 clarifi
USER clarifi
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
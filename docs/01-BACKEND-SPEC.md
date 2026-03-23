# 01 — Backend Specification

## App Factory Pattern

```python
# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings
from app.core.events import on_startup, on_shutdown
from app.api.v1.router import api_v1_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    await on_startup(app)
    yield
    await on_shutdown(app)

def create_app() -> FastAPI:
    app = FastAPI(
        title="Clarifi.ai",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/api/docs" if not settings.is_production else None,
    )
    _setup_middleware(app)
    _setup_routes(app)
    _setup_exception_handlers(app)
    return app

def _setup_middleware(app: FastAPI):
    # Order matters: outermost first
    # 1. Request ID middleware (adds X-Request-ID to every request)
    # 2. Structured logging middleware (logs request/response with request_id)
    # 3. CORS
    # 4. Rate limiting (Redis sliding window)
    # 5. Trusted host (production only)
    pass

def _setup_routes(app: FastAPI):
    app.include_router(api_v1_router, prefix="/api/v1")

def _setup_exception_handlers(app: FastAPI):
    # Map domain exceptions → HTTP responses
    pass

app = create_app()
```

---

## Configuration

```python
# app/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}

    # --- Core ---
    environment: str = "development"
    debug: bool = False
    secret_key: str  # REQUIRED — no default
    allowed_hosts: list[str] = ["localhost"]

    # --- Database ---
    database_url: str = "postgresql+asyncpg://clarifi:clarifi@localhost:5432/clarifi"
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_echo: bool = False

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Auth ---
    access_token_expire_minutes: int = 15      # Shorter than v1's 30
    refresh_token_expire_days: int = 30
    jwt_algorithm: str = "HS256"

    # --- File Storage ---
    storage_backend: str = "local"             # "local" | "s3"
    s3_bucket: str = "clarifi-uploads"
    s3_endpoint_url: str | None = None         # MinIO URL for dev
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    local_upload_dir: str = "/tmp/clarifi-uploads"
    max_file_size_mb: int = 100                # 10x increase from v1

    # --- LLM ---
    llm_provider: str = "gemini"               # "gemini" | "anthropic" | "openai"
    llm_api_key: str | None = None
    llm_model: str = "gemini-2.5-flash"
    llm_max_tokens: int = 2000
    llm_timeout_seconds: int = 30

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:5173"]

    # --- Rate Limiting ---
    rate_limit_per_minute: int = 60
    rate_limit_upload_per_minute: int = 10

    # --- Workers ---
    max_rows_for_sync: int = 10_000            # Below this: process synchronously
    max_rows_for_analysis: int = 500_000       # Hard cap

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
```

---

## Database Models (SQLAlchemy 2.0 Mapped)

### Key Changes from v1
- `file_content` TEXT column → S3 object reference (just store the key)
- Add `Job` model for async task tracking
- Add `AuditLog` for compliance
- Add `DatasetVersion` for edit history (not just latest)
- Use server-side UUID generation
- Add `organization_id` column to User (multi-tenancy prep)

```python
# app/db/models/user.py
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.engine import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)  # Future multi-tenancy
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    datasets: Mapped[list["Dataset"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")
```

```python
# app/db/models/dataset.py
class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(500))
    original_format: Mapped[str] = mapped_column(String(20))
    storage_key: Mapped[str] = mapped_column(String(1000))   # S3 key or local path
    file_size_bytes: Mapped[int] = mapped_column(nullable=True)
    row_count: Mapped[int | None]
    column_count: Mapped[int | None]
    schema_json: Mapped[str | None] = mapped_column(Text)    # Column names + inferred types
    latest_quality_score: Mapped[int | None]
    latest_report_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    owner: Mapped["User"] = relationship(back_populates="datasets")
    jobs: Mapped[list["Job"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_datasets_user_created", "user_id", "created_at"),
    )
```

```python
# app/db/models/job.py
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    job_type: Mapped[str] = mapped_column(String(50))        # "analyze" | "autofix" | "export"
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending → running → completed | failed
    progress: Mapped[int] = mapped_column(default=0)          # 0-100
    result_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    dataset: Mapped["Dataset"] = relationship(back_populates="jobs")
```

---

## Repository Pattern

Every DB interaction goes through a repository — no raw queries in routes.

```python
# app/db/repositories/dataset_repo.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

class DatasetRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, user_id: uuid.UUID, **kwargs) -> Dataset:
        dataset = Dataset(user_id=user_id, **kwargs)
        self.db.add(dataset)
        await self.db.flush()
        return dataset

    async def get_by_id(self, dataset_id: uuid.UUID, user_id: uuid.UUID) -> Dataset | None:
        result = await self.db.execute(
            select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID, limit: int = 20, offset: int = 0) -> list[Dataset]:
        result = await self.db.execute(
            select(Dataset)
            .where(Dataset.user_id == user_id)
            .order_by(Dataset.created_at.desc())
            .limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def update_quality(self, dataset_id: uuid.UUID, score: int, report_json: str):
        dataset = await self.db.get(Dataset, dataset_id)
        if dataset:
            dataset.latest_quality_score = score
            dataset.latest_report_json = report_json
            await self.db.flush()
```

---

## Auth Service (v2 improvements)

```python
# app/core/security.py
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
import jwt  # PyJWT, not python-jose

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)

def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Token type mismatch")
    return payload
```

---

## Async Job System (ARQ)

```python
# app/workers/tasks/analyze.py
import polars as pl
from arq import Retry
from app.engine.pipeline import run_analysis_pipeline
from app.workers.progress import publish_progress

async def analyze_dataset_task(ctx: dict, job_id: str, dataset_id: str, storage_key: str):
    """
    Runs in ARQ worker process. Publishes progress via Redis pub/sub.
    """
    redis = ctx["redis"]
    db_session = ctx["db"]

    try:
        await publish_progress(redis, job_id, status="running", progress=0)

        # 1. Download file from S3/local
        file_bytes = await download_file(storage_key)
        await publish_progress(redis, job_id, progress=10, message="File loaded")

        # 2. Parse into DataFrame
        df = read_file(file_bytes, storage_key)
        await publish_progress(redis, job_id, progress=20, message="Parsed")

        # 3. Run inspection pipeline
        report = run_analysis_pipeline(
            df,
            filename=storage_key.split("/")[-1],
            on_progress=lambda p, msg: publish_progress(redis, job_id, progress=20 + int(p * 0.6), message=msg)
        )
        await publish_progress(redis, job_id, progress=80, message="Analysis complete")

        # 4. LLM enhancement (optional)
        report = await enhance_with_llm(report)
        await publish_progress(redis, job_id, progress=95, message="AI summary generated")

        # 5. Persist result
        await update_job_result(db_session, job_id, dataset_id, report)
        await publish_progress(redis, job_id, status="completed", progress=100)

    except Exception as e:
        await publish_progress(redis, job_id, status="failed", error=str(e))
        raise
```

---

## WebSocket Progress

```python
# app/api/v1/jobs.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import redis.asyncio as aioredis

router = APIRouter(prefix="/jobs", tags=["jobs"])

@router.websocket("/ws/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str):
    await websocket.accept()
    redis = aioredis.from_url(settings.redis_url)
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"job:{job_id}")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"].decode())
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(f"job:{job_id}")
        await redis.close()
```

---

## File Storage Abstraction

```python
# app/services/file_storage.py
from abc import ABC, abstractmethod
import aiofiles
import aioboto3

class FileStorage(ABC):
    @abstractmethod
    async def upload(self, key: str, data: bytes) -> str: ...
    @abstractmethod
    async def download(self, key: str) -> bytes: ...
    @abstractmethod
    async def delete(self, key: str) -> None: ...
    @abstractmethod
    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str: ...

class LocalStorage(FileStorage):
    """For development. Stores files on local disk."""
    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def upload(self, key: str, data: bytes) -> str:
        path = self.base_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)
        return key

    async def download(self, key: str) -> bytes:
        async with aiofiles.open(self.base_dir / key, "rb") as f:
            return await f.read()

class S3Storage(FileStorage):
    """For production. Uses S3-compatible storage (AWS S3, MinIO)."""
    def __init__(self, bucket: str, endpoint_url: str | None = None, **kwargs):
        self.bucket = bucket
        self.session = aioboto3.Session()
        self.endpoint_url = endpoint_url

    async def upload(self, key: str, data: bytes) -> str:
        async with self.session.client("s3", endpoint_url=self.endpoint_url) as s3:
            await s3.put_object(Bucket=self.bucket, Key=key, Body=data)
        return key
    # ... etc

def get_storage() -> FileStorage:
    if settings.storage_backend == "s3":
        return S3Storage(bucket=settings.s3_bucket, endpoint_url=settings.s3_endpoint_url)
    return LocalStorage(base_dir=settings.local_upload_dir)
```

---

## Rate Limiting (Redis Sliding Window)

```python
# app/core/rate_limiter.py
import time
import redis.asyncio as aioredis
from fastapi import Request, HTTPException

class RateLimiter:
    def __init__(self, redis: aioredis.Redis, limit: int, window_seconds: int = 60):
        self.redis = redis
        self.limit = limit
        self.window = window_seconds

    async def check(self, key: str) -> bool:
        now = time.time()
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - self.window)  # Remove old entries
        pipe.zadd(key, {str(now): now})                    # Add current
        pipe.zcard(key)                                     # Count
        pipe.expire(key, self.window)                       # TTL
        results = await pipe.execute()
        count = results[2]
        return count <= self.limit

    def key_for_request(self, request: Request, user_id: str | None = None) -> str:
        identifier = user_id or request.client.host
        return f"ratelimit:{identifier}:{request.url.path}"
```

---

## Error Handling

```python
# app/core/exceptions.py
class ClarifiError(Exception):
    """Base exception for all domain errors."""
    status_code: int = 500
    detail: str = "Internal server error"

class NotFoundError(ClarifiError):
    status_code = 404

class ConflictError(ClarifiError):
    status_code = 409

class ValidationError(ClarifiError):
    status_code = 422

class FileTooLargeError(ClarifiError):
    status_code = 413

class RateLimitExceededError(ClarifiError):
    status_code = 429

class AuthenticationError(ClarifiError):
    status_code = 401

class AuthorizationError(ClarifiError):
    status_code = 403
```

Map to HTTP in a single handler:
```python
@app.exception_handler(ClarifiError)
async def clarifi_error_handler(request: Request, exc: ClarifiError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": type(exc).__name__, "detail": exc.detail, "request_id": request.state.request_id},
    )
```

---

## LLM Service (Provider-Agnostic)

```python
# app/services/llm_service.py
from litellm import acompletion

class LLMService:
    def __init__(self):
        self.model = f"{settings.llm_provider}/{settings.llm_model}"

    async def generate_summary(self, issues_context: str) -> str:
        response = await acompletion(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": issues_context},
            ],
            max_tokens=settings.llm_max_tokens,
            temperature=0.3,
            timeout=settings.llm_timeout_seconds,
        )
        return response.choices[0].message.content

    async def suggest_column_fixes(self, column_name: str, sample_values: list[str], issue_type: str) -> list[dict]:
        """NEW in v2: Per-column intelligent fix suggestions."""
        prompt = f"""Column '{column_name}' has {issue_type} issues.
Sample values: {sample_values[:20]}
Suggest specific fixes as JSON array: [{{"value": "original", "fix": "corrected", "reason": "why"}}]"""

        response = await acompletion(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=1000,
        )
        return json.loads(response.choices[0].message.content)
```

---

## Testing Strategy

```python
# tests/conftest.py
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.main import create_app
from app.db.engine import Base, get_db
from app.config import Settings

TEST_DB_URL = "postgresql+asyncpg://test:test@localhost:5433/clarifi_test"

@pytest.fixture(scope="session")
async def engine():
    eng = create_async_engine(TEST_DB_URL)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()

@pytest.fixture
async def db_session(engine):
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()

@pytest.fixture
async def client(db_session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

---

## Dependencies (`pyproject.toml`)

```toml
[project]
name = "clarifi-backend"
version = "2.0.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "pydantic[email]>=2.9",
    "polars>=1.20",
    "fastexcel>=0.11",
    "xlsxwriter>=3.2",
    "openpyxl>=3.1",
    "python-multipart",
    "PyJWT[crypto]>=2.9",
    "passlib[bcrypt]>=1.7",
    "redis>=5.0",
    "arq>=0.26",
    "litellm>=1.50",
    "aioboto3>=13",
    "aiofiles>=24",
    "structlog>=24",
    "sentry-sdk[fastapi]>=2",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5",
    "httpx>=0.27",
    "ruff>=0.8",
    "mypy>=1.13",
    "factory-boy>=3.3",
]

[tool.ruff]
target-version = "py312"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "ASYNC"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
```

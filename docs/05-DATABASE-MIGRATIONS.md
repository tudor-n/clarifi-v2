# 05 — Database & Migrations Specification

## Schema Overview

v2 replaces `file_history` with a proper `datasets` + `jobs` model. Files are stored in S3, not in TEXT columns.

```
users
├── refresh_tokens (1:N)
├── datasets (1:N)
│   └── jobs (1:N)
└── audit_log (1:N)
```

---

## Migration: v1 → v2

### Step 1: Create new tables (non-destructive)

```python
# alembic/versions/002_v2_schema.py

def upgrade():
    # --- datasets table (replaces file_history) ---
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("original_format", sa.String(20), nullable=False),
        sa.Column("storage_key", sa.String(1000), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("column_count", sa.Integer(), nullable=True),
        sa.Column("schema_json", sa.Text(), nullable=True),
        sa.Column("latest_quality_score", sa.Integer(), nullable=True),
        sa.Column("latest_report_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_datasets_user_created", "datasets", ["user_id", "created_at"])
    op.create_index("ix_datasets_user_id", "datasets", ["user_id"])

    # --- jobs table ---
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("dataset_id", sa.Uuid(), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0"),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_jobs_dataset_id", "jobs", ["dataset_id"])
    op.create_index("ix_jobs_user_status", "jobs", ["user_id", "status"])

    # --- audit_log table ---
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    # --- Update users table: UUID primary key + organization_id ---
    # NOTE: If migrating live data from v1 String(36) to native Uuid,
    # this requires a data migration step. For greenfield v2, use Uuid directly.
    op.add_column("users", sa.Column("organization_id", sa.Uuid(), nullable=True))


def downgrade():
    op.drop_column("users", "organization_id")
    op.drop_table("audit_log")
    op.drop_table("jobs")
    op.drop_table("datasets")
```

### Step 2: Data migration (if upgrading from v1)

```python
# alembic/versions/003_migrate_file_history.py
"""Migrate file_history data to datasets table."""

def upgrade():
    # For each file_history row:
    # 1. Upload file_content to S3 → get storage_key
    # 2. Insert into datasets with storage_key
    # 3. This should be a script, not inline SQL, due to S3 uploads
    pass

def downgrade():
    pass  # One-way migration
```

### Step 3: Drop old tables

```python
# alembic/versions/004_drop_v1_tables.py
def upgrade():
    op.drop_table("file_history")

def downgrade():
    # Recreate file_history if needed
    pass
```

---

## Index Strategy

| Table | Index | Purpose |
|-------|-------|---------|
| users | `email` (unique) | Login lookup |
| users | `username` (unique) | Display name uniqueness |
| datasets | `(user_id, created_at)` | History listing (most recent first) |
| jobs | `(user_id, status)` | "Show me my running jobs" |
| jobs | `dataset_id` | "All jobs for this dataset" |
| refresh_tokens | `token_hash` (unique) | Token validation |
| refresh_tokens | `(user_id, revoked)` | Revoke all for user |
| audit_log | `user_id` | User activity history |
| audit_log | `created_at` | Time-range queries |

---

## Connection Pooling

```python
# app/db/engine.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,        # 20 connections
    max_overflow=settings.db_max_overflow,   # 10 extra under load
    pool_pre_ping=True,                      # Check connection health
    pool_recycle=3600,                       # Recycle connections after 1 hour
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

---

## Backup Strategy

For production PostgreSQL:
- **Continuous WAL archiving** to S3 (point-in-time recovery)
- **Daily pg_dump** stored in S3 with 30-day retention
- **Test restores weekly** — backups that aren't tested aren't backups

```bash
# Cron job example
0 2 * * * pg_dump -Fc clarifi | aws s3 cp - s3://clarifi-backups/daily/$(date +%Y%m%d).dump
```

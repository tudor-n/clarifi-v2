# Clarifi.ai v2 — Master Implementation Plan

## Read Order for Claude Code

1. `00-MASTER-PLAN.md` — This file. Architecture overview and critical decisions.
2. `01-BACKEND-SPEC.md` — Backend rewrite: FastAPI → modular, async-first, task queues.
3. `02-FRONTEND-SPEC.md` — Frontend rewrite: TypeScript, Zustand, component architecture.
4. `03-DATA-ENGINE-SPEC.md` — Core data quality engine: algorithms, scoring, autofix v2.
5. `04-INFRASTRUCTURE-SPEC.md` — Docker, CI/CD, observability, deployment.
6. `05-DATABASE-MIGRATIONS.md` — Schema v2, multi-tenancy prep, audit trails.
7. `06-API-CONTRACT.md` — OpenAPI-first contract, versioning, error taxonomy.

---

## v1 Audit Summary

### What Works Well (Keep)
- Polars for data processing (fast, memory-efficient)
- Inspector pattern for quality checks (extensible)
- JWT + refresh token rotation with theft detection
- Docker multi-stage builds
- Nginx reverse proxy with security headers
- Async SQLAlchemy with PostgreSQL

### Critical Problems in v1

| Area | Problem | Impact |
|------|---------|--------|
| **No task queue** | File analysis blocks the HTTP request thread | Timeouts on large files, no progress feedback |
| **No TypeScript** | Frontend is vanilla JS React | Refactoring is fragile, no compile-time safety |
| **God component** | `App.jsx` is 500+ lines with all state | Impossible to test, maintain, or extend |
| **No caching** | Every re-analysis re-runs from scratch | Wasted compute on unchanged data |
| **No WebSocket** | No real-time progress for long operations | Poor UX on files >1MB |
| **Monolithic backend** | All logic in `api/routes.py` and flat services | Hard to test, hard to scale independently |
| **No tests** | Zero test files in entire codebase | Regressions on every change |
| **LLM is bolted on** | Gemini only generates a 2-sentence summary | Massive underuse of LLM capability |
| **No rate limiting per user** | slowapi uses IP only | Abuse possible, unfair to multi-tenant |
| **File size ceiling** | 10MB hard limit, 50k row cap | Enterprise datasets are 100MB+ |
| **No streaming exports** | Entire file built in memory then sent | OOM on large exports |
| **Session-only workspace** | `sessionStorage` loses work on tab close | Data loss frustration |

---

## v2 Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    NGINX / Caddy                         │
│              (TLS termination, static files)             │
├────────────┬────────────────────────┬───────────────────┤
│            │                        │                   │
│   React    │    FastAPI Gateway     │   WebSocket       │
│   SPA      │    (REST API)          │   Server          │
│            │                        │   (progress)      │
├────────────┴────────────────────────┴───────────────────┤
│                                                         │
│                    Redis                                 │
│         (cache + task broker + pub/sub)                  │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│              Celery / ARQ Workers                        │
│    ┌──────────┐  ┌──────────┐  ┌──────────────┐        │
│    │ Analyze  │  │ AutoFix  │  │ LLM Enhance  │        │
│    │ Worker   │  │ Worker   │  │ Worker        │        │
│    └──────────┘  └──────────┘  └──────────────┘        │
│                                                         │
├──────────────────────┬──────────────────────────────────┤
│                      │                                  │
│    PostgreSQL        │       S3 / MinIO                 │
│    (users, history,  │       (file storage,             │
│     audit, jobs)     │        large datasets)           │
│                      │                                  │
└──────────────────────┴──────────────────────────────────┘
```

---

## Technology Stack Changes

### Backend

| v1 | v2 | Rationale |
|----|-----|-----------|
| FastAPI (monolith) | FastAPI (modular with routers + dependency injection) | Same framework, better structure |
| No task queue | **ARQ** (async Redis queue) | Lightweight, Python-native async, perfect for FastAPI |
| No cache | **Redis** (via `redis.asyncio`) | Cache analysis results, rate limiting, pub/sub for WS |
| No WebSocket | **FastAPI WebSocket** + Redis pub/sub | Real-time progress on analyze/fix jobs |
| Gemini only | **LiteLLM** wrapping Gemini/Claude/OpenAI | Provider-agnostic, fallback chains, cost control |
| `polars` 1.12 | `polars` latest stable | Keep — it's the right tool |
| `python-jose` | **`PyJWT`** + `cryptography` | `python-jose` is unmaintained; PyJWT is actively developed |
| `bcrypt` via raw | **`passlib[bcrypt]`** | Cleaner API, automatic rounds upgrade |
| No file storage | **MinIO** (S3-compatible) for dev, S3 for prod | Files don't belong in TEXT columns |
| SQLite dev default | **PostgreSQL always** (via Docker Compose) | Parity between dev and prod eliminates bugs |
| `slowapi` | **Custom rate limiter** on Redis (sliding window) | Per-user, per-endpoint, configurable |
| No monitoring | **Structlog** + **Sentry** + Prometheus metrics | Structured logging, error tracking, dashboards |

### Frontend

| v1 | v2 | Rationale |
|----|-----|-----------|
| JavaScript | **TypeScript (strict)** | Catch bugs at compile time |
| Props drilling in App.jsx | **Zustand** (global state) + React Query (server state) | Clean separation, no prop threading |
| Vanilla CSS files | **Tailwind CSS** | Utility-first, consistent design tokens, smaller bundle |
| No routing | **React Router v7** | Multi-page: dashboard, analysis, settings, history |
| No data fetching lib | **TanStack Query (React Query)** | Caching, deduplication, background refetching |
| `@tanstack/react-virtual` | Keep (virtualized tables) | Already good |
| `lucide-react` | Keep | Already good |
| No error boundaries per route | **Per-route error boundaries** | Graceful degradation |
| `sessionStorage` workspace | **IndexedDB** via `idb-keyval` + server sync | Survives tab close, syncs when online |
| No form validation | **Zod** + **React Hook Form** | Schema-validated forms |

### Infrastructure

| v1 | v2 | Rationale |
|----|-----|-----------|
| `docker-compose.yml` only | Docker Compose (dev) + **Kubernetes manifests** (prod) | Production-grade orchestration |
| No CI/CD | **GitHub Actions** pipeline | Lint → Test → Build → Push → Deploy |
| No health checks beyond basic | **Liveness + readiness probes** with dependency checks | Proper orchestration health |
| Single nginx config | **Caddy** (auto TLS) or nginx with certbot | Automatic HTTPS |
| No secrets management | **Docker secrets** (dev) / **AWS Secrets Manager** (prod) | No `.env` in production |

---

## Project Structure (v2)

```
clarifi-v2/
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── deploy.yml
├── backend/
│   ├── alembic/
│   │   ├── versions/
│   │   └── env.py
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI app factory
│   │   ├── config.py                  # Pydantic Settings
│   │   ├── dependencies.py            # Shared DI providers
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── v1/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── router.py          # Aggregates all v1 routers
│   │   │   │   ├── auth.py
│   │   │   │   ├── datasets.py        # upload, analyze, autofix, export
│   │   │   │   ├── history.py
│   │   │   │   ├── jobs.py            # Job status polling / WS
│   │   │   │   └── users.py
│   │   │   └── deps.py                # Route-level dependencies
│   │   │
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── security.py            # JWT, password hashing
│   │   │   ├── rate_limiter.py         # Redis sliding window
│   │   │   ├── exceptions.py           # Custom exception hierarchy
│   │   │   └── events.py              # Startup/shutdown hooks
│   │   │
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── engine.py              # Async engine + session factory
│   │   │   ├── models/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── user.py
│   │   │   │   ├── dataset.py
│   │   │   │   ├── job.py
│   │   │   │   └── audit.py
│   │   │   └── repositories/
│   │   │       ├── __init__.py
│   │   │       ├── user_repo.py
│   │   │       ├── dataset_repo.py
│   │   │       └── job_repo.py
│   │   │
│   │   ├── schemas/                    # Pydantic request/response models
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── dataset.py
│   │   │   ├── job.py
│   │   │   └── quality.py
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── auth_service.py
│   │   │   ├── dataset_service.py
│   │   │   ├── file_storage.py         # S3/MinIO abstraction
│   │   │   └── llm_service.py          # LiteLLM wrapper
│   │   │
│   │   ├── engine/                     # Data quality engine
│   │   │   ├── __init__.py
│   │   │   ├── pipeline.py             # Orchestrator
│   │   │   ├── reader.py               # File → Polars DataFrame
│   │   │   ├── scorer.py               # Quality scoring
│   │   │   ├── inspectors/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py
│   │   │   │   ├── completeness.py
│   │   │   │   ├── uniqueness.py
│   │   │   │   ├── consistency.py
│   │   │   │   ├── accuracy.py
│   │   │   │   ├── format.py
│   │   │   │   └── registry.py         # Auto-discover inspectors
│   │   │   ├── fixers/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py
│   │   │   │   ├── whitespace.py
│   │   │   │   ├── casing.py
│   │   │   │   ├── dates.py
│   │   │   │   ├── emails.py
│   │   │   │   ├── nulls.py
│   │   │   │   ├── numeric.py
│   │   │   │   ├── cross_column.py
│   │   │   │   └── registry.py
│   │   │   └── profiler.py             # Column type inference
│   │   │
│   │   └── workers/
│   │       ├── __init__.py
│   │       ├── celery_app.py           # Or arq worker config
│   │       ├── tasks/
│   │       │   ├── analyze.py
│   │       │   ├── autofix.py
│   │       │   └── export.py
│   │       └── progress.py             # Redis pub/sub progress updates
│   │
│   ├── tests/
│   │   ├── conftest.py                 # Fixtures: test DB, test client, factories
│   │   ├── unit/
│   │   │   ├── test_inspectors.py
│   │   │   ├── test_fixers.py
│   │   │   ├── test_scorer.py
│   │   │   └── test_security.py
│   │   ├── integration/
│   │   │   ├── test_auth_flow.py
│   │   │   ├── test_dataset_flow.py
│   │   │   └── test_history.py
│   │   └── fixtures/
│   │       ├── clean_dataset.csv
│   │       ├── messy_dataset.csv
│   │       └── edge_cases.xlsx
│   │
│   ├── alembic.ini
│   ├── pyproject.toml                  # Single config: deps, linting, testing
│   ├── Dockerfile
│   └── docker-compose.dev.yml
│
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── router.tsx                  # React Router config
│   │   │
│   │   ├── api/
│   │   │   ├── client.ts              # Axios/fetch wrapper with interceptors
│   │   │   ├── auth.ts                # Auth API calls
│   │   │   ├── datasets.ts            # Dataset API calls
│   │   │   └── history.ts
│   │   │
│   │   ├── stores/
│   │   │   ├── authStore.ts           # Zustand: user, tokens
│   │   │   ├── datasetStore.ts        # Zustand: current dataset, edits, undo
│   │   │   └── uiStore.ts            # Zustand: modals, sidebar, theme
│   │   │
│   │   ├── hooks/
│   │   │   ├── useAuth.ts
│   │   │   ├── useDataset.ts          # React Query hooks
│   │   │   ├── useWebSocket.ts        # Job progress WS
│   │   │   └── useUndoRedo.ts
│   │   │
│   │   ├── components/
│   │   │   ├── ui/                    # Primitives: Button, Input, Modal, Badge
│   │   │   ├── layout/               # Shell, Sidebar, Topbar
│   │   │   ├── auth/                  # LoginForm, RegisterForm, AuthGuard
│   │   │   ├── dataset/              # DataTable, CellEditor, ColumnHeader
│   │   │   ├── quality/              # ScoreRing, CategoryBars, IssueCard
│   │   │   └── history/              # HistoryList, HistoryItem
│   │   │
│   │   ├── pages/
│   │   │   ├── DashboardPage.tsx      # Upload + history
│   │   │   ├── AnalysisPage.tsx       # Table + quality panel
│   │   │   ├── SettingsPage.tsx       # User preferences
│   │   │   └── NotFoundPage.tsx
│   │   │
│   │   ├── lib/
│   │   │   ├── constants.ts
│   │   │   ├── csv.ts                 # CSV encode/decode utils
│   │   │   └── format.ts             # Number, date formatting
│   │   │
│   │   └── types/
│   │       ├── api.ts                 # API response types (generated from OpenAPI)
│   │       ├── dataset.ts
│   │       └── quality.ts
│   │
│   ├── index.html
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── package.json
│   └── Dockerfile
│
├── docker/
│   ├── nginx.conf
│   └── redis.conf
├── docker-compose.yml                  # Production
├── docker-compose.dev.yml              # Development (hot reload)
├── Makefile                            # Common commands
└── README.md
```

---

## Implementation Order

### Phase 1: Foundation (Week 1-2)
1. Set up monorepo with `pyproject.toml` and `package.json`
2. Backend: FastAPI app factory, config, DB models, Alembic migrations
3. Backend: Auth service (PyJWT, passlib, refresh rotation)
4. Frontend: Vite + TypeScript + Tailwind + React Router scaffold
5. Frontend: Zustand stores + API client + auth flow
6. Docker Compose dev environment (Postgres + Redis + MinIO)
7. CI pipeline: lint + type-check + unit tests

### Phase 2: Core Engine (Week 3-4)
1. Backend: File reader (Polars) with streaming for large files
2. Backend: Inspector registry + all inspectors (ported from v1, improved)
3. Backend: Fixer registry + all fixers (ported from v1, improved)
4. Backend: Quality scorer v2 (see `03-DATA-ENGINE-SPEC.md`)
5. Backend: ARQ workers for analyze + autofix
6. Backend: Redis pub/sub for progress updates
7. Frontend: WebSocket hook for job progress

### Phase 3: UI (Week 5-6)
1. Frontend: Dashboard page (upload + history)
2. Frontend: Analysis page (virtualized table + quality sidebar)
3. Frontend: Cell editing with undo/redo (Zustand middleware)
4. Frontend: Search, filter, sort on table
5. Frontend: Quarantine tab with merge workflow
6. Frontend: Export flow (streaming download)

### Phase 4: Polish & Scale (Week 7-8)
1. Backend: LLM-powered suggestions (column-level, not just summary)
2. Backend: Streaming export for large files
3. Backend: S3 file storage integration
4. Frontend: IndexedDB persistence for offline resilience
5. Integration tests for all critical paths
6. Load testing with k6 or locust
7. Kubernetes manifests + Helm chart
8. Production deployment checklist

---

## Non-Negotiable Quality Gates

Every PR must pass:
- `ruff check` + `ruff format` (backend)
- `eslint` + `tsc --noEmit` (frontend)
- Unit tests: >80% coverage on engine/
- Integration tests: auth flow, upload-analyze-export flow
- No `any` types in TypeScript (except explicit `unknown`)
- All API endpoints documented in OpenAPI schema
- Database migrations are reversible (up + down)

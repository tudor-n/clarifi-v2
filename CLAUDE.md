# ClariFi v2 — Claude Code instructions

## What this project is
Data quality SaaS. FastAPI backend + React/TS frontend + async worker pipeline.
v2 rewrites a working v1. The specs in docs/ are authoritative — read them before acting.

## Spec files (read before working in that domain)
- Backend patterns → docs/01-BACKEND-SPEC.md
- Frontend patterns → docs/02-FRONTEND-SPEC.md
- Data engine → docs/03-DATA-ENGINE-SPEC.md
- Infrastructure → docs/04-INFRASTRUCTURE-SPEC.md
- DB migrations → docs/05-DATABASE-MIGRATIONS.md
- API contract → docs/06-API-CONTRACT.md

## Dev environment
```bash
make dev          # starts postgres + redis + minio + backend + frontend
make test         # runs all tests
make migrate      # alembic upgrade head
make lint         # ruff + eslint
```

## Architecture rules (never violate)
- All DB access goes through repositories — no raw queries in routes
- No business logic in routes — routes call services, services call repos
- All new endpoints need a Pydantic schema in schemas/, not inline
- Workers (ARQ) are the only place analysis/autofix runs — never synchronously in a route
- No `any` in TypeScript — use `unknown` + type guard
- Every route must have a rate limit applied

## Patterns already decided (don't re-debate these)
- Auth: PyJWT + passlib[bcrypt], access token 15min, refresh 30d, HttpOnly cookie
- Queue: ARQ (not Celery) — see workers/celery_app.py for WorkerSettings pattern  
- Storage: FileStorage ABC with LocalStorage / S3Storage implementations
- LLM: LiteLLM wrapper in services/llm_service.py — never call provider SDK directly
- Frontend state: Zustand for client state, TanStack Query for server state — no mixing
- Error handling: raise ClarifiError subclasses, the handler in main.py maps them to HTTP

## Code style
- Python: ruff, line-length 120, strict mypy
- TypeScript: strict mode, no `any`, Zod for runtime validation
- Test files mirror source structure: tests/unit/test_inspectors.py ↔ app/engine/inspectors/

## What to do when specs conflict with the existing code
The spec wins. The spec is the target state.

## What NOT to do
- Don't create a new top-level module without checking the project structure in 00-MASTER-PLAN.md
- Don't add dependencies not in pyproject.toml without asking
- Don't skip writing tests for anything in app/engine/ (>80% coverage required)
- Don't put file contents in TEXT database columns — use storage_key + FileStorage
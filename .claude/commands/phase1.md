We are implementing Phase 1 of ClariFi v2 (Foundation).

Read the full context:
@docs/00-MASTER-PLAN.md (Phase 1 section)
@docs/01-BACKEND-SPEC.md
@docs/05-DATABASE-MIGRATIONS.md
@docs/06-API-CONTRACT.md

Phase 1 checklist:
- [ ] pyproject.toml + package.json scaffold
- [ ] FastAPI app factory (main.py, config.py, middleware stack)
- [ ] DB models: User, Dataset, Job, AuditLog, RefreshToken
- [ ] Alembic migration 001 (initial schema)
- [ ] Auth service: register, login, refresh, logout
- [ ] Repository layer: UserRepo, DatasetRepo, JobRepo
- [ ] Frontend: Vite + TS + Tailwind + React Router scaffold
- [ ] Zustand stores + API client with interceptors
- [ ] Auth pages: Login, Register with Zod validation
- [ ] Docker Compose dev environment
- [ ] GitHub Actions CI: lint + type-check

Current task: $ARGUMENTS
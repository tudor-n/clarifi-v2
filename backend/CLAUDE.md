# Backend context

## Key files to understand before touching anything
- app/config.py — all settings, never hardcode values
- app/core/exceptions.py — raise these, not raw HTTPException
- app/db/engine.py — session factory, use get_db() dependency
- app/dependencies.py — shared DI (current_user, rate_limiter, storage)

## Repository pattern — required for all DB access
async def get_by_id(self, id: uuid.UUID, user_id: uuid.UUID) -> Model | None:
    # Always scope by user_id — no cross-user data leaks

## ARQ worker pattern
async def analyze_task(ctx: dict, dataset_id: str, user_id: str) -> dict:
    # ctx["db"] and ctx["redis"] are injected — see workers/celery_app.py
    # Publish progress via workers/progress.py, not direct Redis writes

## Testing requirements
- Use conftest.py fixtures — never create a real DB in unit tests
- Mock FileStorage and LLMService in all integration tests
- Every inspector must have test_<name>.py with: empty col, all-null, large input
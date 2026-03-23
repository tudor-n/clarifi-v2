.PHONY: dev down logs shell-db shell-redis migrate migrate-new test-backend test-frontend test lint-backend lint-frontend lint build deploy

dev:
	docker compose -f docker-compose.dev.yml up --build

down:
	docker compose -f docker-compose.dev.yml down -v

logs:
	docker compose -f docker-compose.dev.yml logs -f

shell-db:
	docker compose -f docker-compose.dev.yml exec postgres psql -U clarifi

shell-redis:
	docker compose -f docker-compose.dev.yml exec redis redis-cli

migrate:
	cd backend && alembic upgrade head

migrate-new:
	cd backend && alembic revision --autogenerate -m "$(MSG)"

test-backend:
	cd backend && pytest tests/ -v --cov=app

test-frontend:
	cd frontend && npm run typecheck && npm run lint

test: test-backend test-frontend

lint-backend:
	cd backend && ruff check . && ruff format --check .

lint-frontend:
	cd frontend && npm run lint

lint: lint-backend lint-frontend

build:
	docker compose build

deploy:
	docker compose up -d

.PHONY: dev down logs shell-db shell-redis

dev:
	docker compose -f docker-compose.dev.yml up

down:
	docker compose -f docker-compose.dev.yml down

logs:
	docker compose -f docker-compose.dev.yml logs -f

shell-db:
	docker compose -f docker-compose.dev.yml exec postgres psql -U clarifi

shell-redis:
	docker compose -f docker-compose.dev.yml exec redis redis-cli
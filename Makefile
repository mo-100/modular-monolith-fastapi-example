.PHONY: up run down logs migrate test

up:
	docker compose up -d --build

run:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f app

migrate:
	docker compose run --rm app python -m scripts.migrate upgrade all

test:
	docker compose run --rm test

OLLAMA_MODEL ?= qwen2.5:72b
COMPOSE_MULTIUSER = docker compose -f docker-compose.yml -f docker-compose.dev-ui.yml -f docker-compose.multiuser.yml

.PHONY: install dev test lint format env up up-ui ollama-model ground-truth tokens down migrate migration \
	multiuser-env up-multiuser multiuser-config down-multiuser

install:
	uv sync

migrate:
	uv run alembic upgrade head

migration:
	uv run alembic revision --autogenerate -m "$(m)"

dev:
	uv run uvicorn demo.main:app --reload --host 0.0.0.0 --port 8000

test:
	uv run pytest -v

lint:
	uv run ruff check .
	uv run mypy src

format:
	uv run ruff format .
	uv run ruff check --fix .

env:
	@test ! -e .env || { echo ".env already exists, keeping it"; exit 1; }
	@sed -e "s/^HERMES_API_SERVER_KEY=.*/HERMES_API_SERVER_KEY=$$(openssl rand -hex 24)/" \
	     -e "s/^HERMES_UID=.*/HERMES_UID=$$(id -u)/" \
	     -e "s/^HERMES_GID=.*/HERMES_GID=$$(id -g)/" env.example > .env
	@chmod 600 .env
	@echo ".env created"

up:
	docker compose up -d

up-ui:
	docker compose -f docker-compose.yml -f docker-compose.dev-ui.yml up -d

ollama-model:
	docker exec demo-ollama ollama pull $(OLLAMA_MODEL)

ground-truth:
	uv run --group ground-truth python scripts/ground_truth.py

tokens:
	@docker exec -i demo-hermes python3 - $(or $(N),10) $(if $(ALL),--all) < scripts/hermes_tokens.py

down:
	docker compose -f docker-compose.yml -f docker-compose.dev-ui.yml down

# --- Multi-user access (proxy + LDAP), see README ---

# Add the multi-user secrets and DEMO_HOST to an existing .env (keeps values already set).
multiuser-env:
	@test -e .env || { echo "No .env: run make env first"; exit 1; }
	@for v in USER_JWT_SECRET LLDAP_JWT_SECRET LLDAP_KEY_SEED LLDAP_ADMIN_PASSWORD; do \
	  grep -q "^$$v=" .env || echo "$$v=$$(openssl rand -hex 24)" >> .env; done
	@grep -q '^DEMO_HOST=' .env || echo "DEMO_HOST=$$(hostname -I | cut -d' ' -f1)" >> .env
	@grep '^DEMO_HOST=' .env

up-multiuser:
	$(COMPOSE_MULTIUSER) up -d --build

# Open WebUI keeps LDAP/sign-up settings in its database after the first start:
# copy the current values into it and restart.
multiuser-config:
	@docker exec -i demo-ui-dev python3 - < scripts/openwebui_auth_config.py
	docker restart demo-ui-dev

down-multiuser:
	$(COMPOSE_MULTIUSER) down

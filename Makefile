OLLAMA_MODEL ?= qwen2.5:72b
COMPOSE_MULTIUSER = docker compose -f docker-compose.yml -f docker-compose.dev-ui.yml -f docker-compose.multiuser.yml

.PHONY: install dev test lint format env up up-ui ollama-model share-capture tokens down migrate migration \
	multiuser-env up-multiuser multiuser-config down-multiuser quiz-reset

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

# Upload a capture to the datalake visible to every user (multi-user mode); prints its capture_id.
SHARED_CAPTURE ?= data/CryLock_final.pcap
share-capture:
	@curl -fsS -F "file=@$(SHARED_CAPTURE)" "http://127.0.0.1:8000/v1/datalake/ingest?shared=true"; echo

tokens:
	@docker exec -i demo-hermes python3 - $(or $(N),10) $(if $(ALL),--all) < scripts/hermes_tokens.py

down:
	docker compose -f docker-compose.yml -f docker-compose.dev-ui.yml down

# --- Multi-user access (proxy + LDAP), see README ---

# Add the multi-user secrets and DEMO_HOST to an existing .env (keeps values already set).
multiuser-env:
	@test -e .env || { echo "No .env: run make env first"; exit 1; }
	@for v in USER_JWT_SECRET LLDAP_JWT_SECRET LLDAP_KEY_SEED LLDAP_ADMIN_PASSWORD QUIZ_SECRET_KEY; do \
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

# Empty the seminar quiz (attempts, hints, points, ranking) after typing 'reset'. Open sessions stay valid.
# FORCE=1 skips the question.
QUIZ_DB_PY = import sqlite3; db = sqlite3.connect('/data/quiz.db')
quiz-reset:
	@n=$$(docker exec demo-quiz python -c "$(QUIZ_DB_PY); print(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0])") || exit 1; \
	if [ "$(FORCE)" != "1" ]; then \
	  printf "This deletes %s quiz attempts (points and ranking). Type 'reset' to continue: " "$$n"; \
	  read answer; [ "$$answer" = "reset" ] || { echo "Cancelled, nothing deleted"; exit 1; }; \
	fi; \
	docker exec demo-quiz python -c "$(QUIZ_DB_PY); print('Deleted', db.execute('DELETE FROM attempts').rowcount, 'attempts'); db.execute('DELETE FROM hints'); db.commit()"

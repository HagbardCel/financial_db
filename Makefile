SHELL := /usr/bin/env bash

ENV_FILE := .devcontainer/.env
COMPOSE_FILE := .devcontainer/docker-compose.yml
COMPOSE := docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE)
HOST_POSTGRES_HOST := localhost

ifneq ("$(wildcard $(ENV_FILE))","")
include $(ENV_FILE)
export
endif

.PHONY: help require-env db-up db-down db-init refresh dashboard test

help:
	@printf '%s\n' \
		'Local workflow targets:' \
		'  make db-up      Start the PostgreSQL service for host-side development' \
		'  make db-down    Stop the PostgreSQL service' \
		'  make db-init    Create or update the database schema' \
		'  make refresh    Run the configured data refresh workflow' \
		'  make dashboard  Start the Streamlit dashboard' \
		'  make test       Run the pytest suite' \
		'' \
		'DB-backed targets read .devcontainer/.env and use POSTGRES_HOST=localhost on the host.'

require-env:
	@test -f "$(ENV_FILE)" || { \
		echo "Missing $(ENV_FILE). Create it with the local PostgreSQL and provider settings."; \
		exit 1; \
	}
	@test -n "$(PROJECT_DATA_DIR)" || { \
		echo "PROJECT_DATA_DIR must be set in $(ENV_FILE)"; \
		exit 1; \
	}

db-up: require-env
	$(COMPOSE) up -d db

db-down: require-env
	$(COMPOSE) down

db-init: require-env
	POSTGRES_HOST=$(HOST_POSTGRES_HOST) uv run python db_utils/db_setup.py

refresh: require-env
	POSTGRES_HOST=$(HOST_POSTGRES_HOST) uv run python -m data_fetchers.refresh_all

dashboard: require-env
	POSTGRES_HOST=$(HOST_POSTGRES_HOST) uv run streamlit run dashboard/app.py

test:
	uv run pytest tests/

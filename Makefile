.DEFAULT_GOAL := help
COMPOSE      := docker compose
DEV_COMPOSE  := docker compose -f docker-compose.yml -f docker-compose.dev.yml
VERSION      := $(shell cat VERSION)

.PHONY: help install up dev down logs ps build pull test lint fmt shell psql backup restore release clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## First-time setup (secrets, TLS cert, images, start)
	./scripts/install.sh --build

up: ## Start the production stack
	$(COMPOSE) up -d

dev: ## Start the stack with live reload
	$(DEV_COMPOSE) up

down: ## Stop the stack (keeps data)
	$(COMPOSE) down

logs: ## Tail all logs
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

build: ## Rebuild all images
	$(COMPOSE) build --pull

pull: ## Pull published images from GHCR
	$(COMPOSE) pull

test: ## Run backend tests inside the container
	$(COMPOSE) run --rm --entrypoint sh backend -c "pip install -q pytest pytest-cov && pytest"

lint: ## Lint the backend
	$(COMPOSE) run --rm --entrypoint sh backend -c "pip install -q ruff && ruff check app"

fmt: ## Auto-format the backend
	$(COMPOSE) run --rm --entrypoint sh backend -c "pip install -q ruff && ruff check --fix app && ruff format app"

shell: ## Open a shell in the backend container
	$(COMPOSE) exec backend sh

psql: ## Open a psql session
	$(COMPOSE) exec postgres psql -U csap -d csap

backup: ## Back up database and artifacts
	./scripts/backup.sh

release: ## Tag and push a release (triggers the GHCR publish workflow)
	git tag -a v$(VERSION) -m "CSAP $(VERSION)"
	git push origin v$(VERSION)

clean: ## Stop the stack and delete all data volumes
	./scripts/uninstall.sh --purge

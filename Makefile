.DEFAULT_GOAL := help
SHELL := /bin/bash

PY  ?= python3
PIP ?= $(PY) -m pip

.PHONY: help setup backend frontend test lint typecheck eval eval-baseline calibrate up down logs clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Install backend + frontend dependencies for local development
	cd backend && $(PIP) install -r requirements-dev.txt
	cd frontend && npm install
	@test -f .env || cp .env.example .env
	@echo "Ready. Run 'make backend' and 'make frontend' in two terminals."

backend: ## Run the API with autoreload on :8000
	cd backend && $(PY) -m uvicorn app.main:app --reload --port 8000

frontend: ## Run the Next.js dev server on :3000
	cd frontend && npm run dev

worker: ## Run a Celery worker (needs REDIS_URL)
	cd backend && celery -A app.workers.celery_app.celery_app worker --loglevel=info

test: ## Run the backend test suite
	cd backend && $(PY) -m pytest -q

test-cov: ## Run tests with a coverage report
	cd backend && $(PY) -m pytest --cov=app --cov-report=term-missing

lint: ## Lint the backend
	cd backend && $(PY) -m ruff check app tests

typecheck: ## Typecheck the frontend
	cd frontend && npm run typecheck

eval: ## Evaluate the currently configured engine on the gold set
	cd backend && $(PY) -m app.evaluation.runner --name "make eval"

eval-baseline: ## Evaluate the rule-based baseline (the floor the LLM must beat)
	cd backend && $(PY) -m app.evaluation.runner --name "baseline" --rule-engine

calibrate: ## Fit the confidence calibrator and write data/calibration.json
	cd backend && $(PY) -m app.evaluation.runner --name "calibration fit" --fit-calibration

up: ## Start the full stack in Docker
	docker compose up --build

down: ## Stop the stack
	docker compose down

logs: ## Tail the API logs
	docker compose logs -f api worker

clean: ## Remove caches, build output and local databases
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/.mypy_cache backend/data/*.db
	rm -rf frontend/.next

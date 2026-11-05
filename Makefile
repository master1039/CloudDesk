UV ?= uv
HOST ?= 0.0.0.0
PORT ?= 8000
RELOAD ?= --reload

.PHONY: help setup seed ingest backend test lint format

help:
	@echo "CloudDesk development commands"
	@echo "  make setup    Create .venv, install locked dependencies, and copy .env.example"
	@echo "  make seed     Create the demo database and load sample data once"
	@echo "  make ingest   Recreate and populate the configured knowledge index"
	@echo "  make backend  Run FastAPI on http://localhost:$(PORT)"
	@echo "  make test     Run the offline pytest suite"
	@echo "  make lint     Run Ruff checks and formatting validation"
	@echo "  make format   Apply Ruff lint fixes and formatting"

setup:
	$(UV) sync --all-groups
	$(UV) run python -c "from pathlib import Path; import shutil; target = Path('.env'); target.exists() or shutil.copyfile('.env.example', target)"

seed:
	$(UV) run python backend/seed.py

ingest:
	$(UV) run python -c "import sys; sys.path.insert(0, 'backend'); from rag.ingest import main; main()"

backend:
	$(UV) run uvicorn app.main:app --app-dir backend --host $(HOST) --port $(PORT) $(RELOAD)

test:
	$(UV) run pytest

lint:
	$(UV) run ruff check backend tests main.py
	$(UV) run ruff check rag
	$(UV) run ruff format --check backend tests main.py
	$(UV) run ruff format --check rag

format:
	$(UV) run ruff check --fix backend tests main.py
	$(UV) run ruff check --fix rag
	$(UV) run ruff format backend tests main.py
	$(UV) run ruff format rag

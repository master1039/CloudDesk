# CloudDesk

<!-- Written by Euron Code project setup. Run /init to let the model fill in the details. -->

Stack: Python, FastAPI, pytest, SQLAlchemy, LangChain

## Commands
- `pip install -e .`
- `python -m pytest`
- `make help`
- `make setup`
- `make seed`
- `make ingest`
- `make backend`
- `make test`

## Layout
```
agents/  (10 files)
backend/  (52 files)
database/  (4 files)
datasets/  (1 files)
docs/  (7 files)
frontend/  (1 files)
integrations/  (5 files)
internal/  (7 files)
  design_evolution/
  explain_codebase/
  knowledge_transfer/
memory/  (4 files)
rag/  (6 files)
sample_data/  (23 files)
tests/  (45 files)
AGENTS.md
CLAUDE.md
Git_GitHub_Workflow_Guide.md
main.py
Makefile
MEMORY.md
PLAN.md
PLAN_PHASE.md
pyproject.toml
README.md
...
```

Entry points: main.py, backend/app/main.py

## Conventions
- (add the conventions of this project here)

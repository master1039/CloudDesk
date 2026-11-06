---
paths: ["**/*.py"]
---
- Follow PEP 8 and the project's formatter/linter (ruff or black if configured).
- Add type hints to new and changed public functions.
- Prefer `pathlib`, f-strings and context managers; never use a bare `except:`.
- Install packages only into the project's virtual environment, never globally, and only when asked.

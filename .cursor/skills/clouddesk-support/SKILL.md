---
name: clouddesk-support
description: Implement and review CloudDesk autonomous-support features while preserving its layer boundaries, deterministic policy gates, offline demo path, contract synchronization, and honest delivery status. Use for backend, frontend, agent, RAG, memory, integration, testing, or deployment work in this repository.
---

# CloudDesk support development

Treat the repository-root `CLAUDE.md` as the source of truth. Before changing behavior, read the relevant requirement in `PLAN.md`, the active phase in `PLAN_PHASE.md`, the task row in `TASKS.md`, and the current facts in `MEMORY.md`.

## Choose the work from repository state

- Continue an explicitly requested task even if it is not the next tracker row, but call out unmet dependencies.
- Otherwise choose the first unblocked `not started` task in `TASKS.md`.
- Mark a task or phase `implemented` only after its code and tests exist.
- Mark it `validated locally` only after the documented checks pass on this machine.
- Never infer that GitHub Actions ran or that a cloud deployment occurred.

## Implement within the architecture

- Keep HTTP/auth/validation in `backend/app/api/`, orchestration in services, and SQL in repositories.
- Keep `backend/app/core/` independent of `agents/` and integrations independent of core.
- Put model-independent policy in `agents/rules.py` or `backend/app/tools/policy.py`.
- Use Pydantic structured outputs and the shared `call_structured` path for model calls.
- Execute tools only through `ToolRegistry`; actions in a resolution plan must come from deterministic planning.
- Wrap all external or customer-controlled content as untrusted input.
- Route money, account changes, deletion, disputes, and setting resets through recorded approval or the defined safe escalation path.
- Keep LangGraph node returns partial. Append reducer values and keep work before `interrupt()` small and idempotent.
- Use memory facades, scrub every durable note, and never store secrets, raw ticket bodies, or another customer's data.

## Keep contracts synchronized

For an HTTP shape change, update all three in one change:

1. `docs/API_CONTRACT.md`
2. `backend/app/schemas/`
3. `frontend/lib/types.ts`

For a schema change, add an additive `database/migrations/000N_<name>.sql` and update `backend/app/models/entities.py` plus `database/schema.sql`. Do not rewrite an applied migration.

## Verify proportionally

- Add or update a test that names the relevant F/N requirement.
- Run focused tests while iterating, then the available phase checkpoint.
- Tests must run with no network and no API key using the fake LLM, memory vector store, fakeredis, temporary SQLite, and `CHECKPOINT_DB_PATH=:memory:`.
- Preserve the safety scenarios: CD-1002 pauses for approval; CD-1005 escalates by rule; CD-1013 stays untrusted data; viewers receive 403 for actions.
- For frontend work, run lint/tests and perform the documented browser flow when the local services exist.
- For delivery work, validate Compose/Terraform locally without claiming a deployment.

## Finish the change

- Update `TASKS.md` only to the status demonstrated by evidence.
- Update `PLAN_PHASE.md` when phase exit criteria are achieved.
- Update `MEMORY.md` when a locked decision or implementation, validation, CI, credential, or deployment fact changes.
- State exactly what was verified and what remains unverified.

Read `docs/ARCHITECTURE.md` when changing boundaries or runtime flows. Read `docs/API_CONTRACT.md` for any route, payload, status-code, or frontend API-client work.

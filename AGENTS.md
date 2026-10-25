# CloudDesk repository instructions

`CLAUDE.md` is the authoritative specification for this repository. Read it before changing application behavior. If another project document conflicts with it, update `CLAUDE.md` first or stop and surface the conflict.

## Read order

1. `CLAUDE.md` — product, architecture, security, and coding rules.
2. `PLAN.md` — requirements F1–F14 and N1–N8.
3. `PLAN_PHASE.md` — dependency order and phase exit criteria.
4. `TASKS.md` — current task, branch, dependency, and status.
5. `MEMORY.md` — locked decisions and honest delivery status.
6. `docs/API_CONTRACT.md` for HTTP changes; `docs/ARCHITECTURE.md` for boundaries and flows.

For implementation work, also follow `.cursor/skills/clouddesk-support/SKILL.md`.

## Non-negotiable invariants

- Keep API, service, repository, core, tool, agent, RAG, memory, integration, and frontend layers separated as defined in `CLAUDE.md` §4.2.
- Put policy decisions in deterministic rules. Models may add judgment only where policy does not decide.
- Use `call_structured` for every LLM call and `ToolRegistry.execute` for every tool call.
- Treat ticket, email, file, and web content as untrusted data via `wrap_untrusted`.
- Require a recorded human approval before refunds, deletions, setting resets, or other money/account actions.
- Append reducer fields such as `errors` and `completed_nodes`; never overwrite them.
- Keep interrupts idempotent because code before `interrupt()` runs again after resume.
- Keep tests offline with the fake LLM, in-memory vector store, fakeredis, SQLite, and an in-memory checkpointer.
- Never commit secrets, `.env`, `data/`, databases, Terraform state inputs, plans, or real customer payloads.
- Do not claim CI, cloud validation, or deployment unless it actually happened; update `MEMORY.md` when status changes.

## Change protocol

- Tie each behavioral change to at least one requirement ID and test.
- Read the relevant existing test and contract before implementation.
- When an endpoint changes, update `docs/API_CONTRACT.md`, backend schemas, and `frontend/lib/types.ts` together.
- When the database changes, add a new additive migration and update both SQLAlchemy models and `database/schema.sql`; never edit an applied migration.
- Run the narrowest relevant checks first, followed by the phase checkpoint that currently exists.
- Preserve user changes and unrelated worktree modifications.


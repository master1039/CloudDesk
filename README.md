# CloudDesk

CloudDesk is an autonomous customer-support and resolution platform for a fictional SaaS product. It helps support agents understand tickets, retrieve evidence, troubleshoot issues, propose grounded replies, and safely execute or escalate resolutions. Money and account changes always require recorded human approval.

The repository currently includes validated runtime, persistence/demo-data, and identity/request-guard phases, including JWT/RBAC, demo authentication, Redis-backed limiting, and durable audit records. Domain APIs, agents, the frontend, containers, CI, and cloud infrastructure remain planned. See [MEMORY.md](MEMORY.md) for the honest current status.

## Target stack

- Next.js 15, TypeScript, and Tailwind for the agent console.
- FastAPI, Pydantic v2, and SQLAlchemy 2 for the API and persistence layers.
- LangGraph with six specialist agents for workflow orchestration.
- PostgreSQL/SQLite, Redis/fakeredis, and Qdrant/in-memory implementations.
- A fake LLM and fake embeddings for fully offline tests and demos.

## Read before contributing

1. [CLAUDE.md](CLAUDE.md) — authoritative product and engineering specification.
2. [AGENTS.md](AGENTS.md) — concise repository instructions for coding agents.
3. [PLAN.md](PLAN.md) — requirements and project-level acceptance criteria.
4. [PLAN_PHASE.md](PLAN_PHASE.md) — ordered 13-phase implementation plan.
5. [TASKS.md](TASKS.md) — branch-level execution tracker.
6. [MEMORY.md](MEMORY.md) — locked decisions and honest delivery status.
7. [Architecture](docs/ARCHITECTURE.md) and [API contract](docs/API_CONTRACT.md).

## Local workflow

Phases 1 and 2 provide these commands:

```powershell
make setup
make seed
make backend
make test
make lint
```

Demo authentication uses `admin@clouddesk.demo`, `sam.agent@clouddesk.demo`, or
`vic.viewer@clouddesk.demo` with the intentionally public local password `clouddesk-demo`.

The following commands are planned for later phases and do not exist yet:

```powershell
make ingest
make demo
make demo TICKET=CD-1005
```

Frontend checks, once the frontend exists:

```powershell
Set-Location frontend
npm run lint
npm run test -- --run
npm run build
```

Delivery checks, once Phase 13 exists:

```powershell
docker compose config -q
docker compose up --build
make terraform-validate
$env:BASE_URL = "http://localhost:8000"
make smoke
```

On Windows, use `.venv\Scripts\python.exe`, put `backend` on `PYTHONPATH`, and set `PYTHONIOENCODING=utf-8` when running symbol-rich CLI output.

## Safety guarantees

- Ticket and external content is always treated as untrusted data.
- Policy rules override model judgment for disputes, deletion, security, data loss, legal cases, and enterprise outages.
- Refunds, account changes, deletion, and setting resets cannot execute without approval.
- A viewer cannot run workflows, reply, approve, reject, or escalate.
- Secrets and raw ticket bodies never enter customer memory, logs, frontend bundles, or version control.
- Cloud files or a merge to `main` do not count as a deployment; only actual verified state is reported.

## Git flow

Feature and bugfix branches target `development`; `development` promotes to `testing`, then `testing` promotes to `main`. Consult [Git_GitHub_Workflow_Guide.md](Git_GitHub_Workflow_Guide.md) before creating branches or pull requests.

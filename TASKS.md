# TASKS.md — CloudDesk implementation tracker

Execution tracker derived from `PLAN_PHASE.md`. `CLAUDE.md` wins if any row drifts. Work from `development`; one row maps to one `feature/<name>` branch and one pull request. Do not mark a task complete from intention.

Status values: `not started`, `in progress`, `implemented`, `validated locally`, `blocked`.

## Phase 1 — Runtime skeleton

| ID | Task | Branch | Depends on | Requirements | Status |
|---|---|---|---|---|---|
| P1-1 | Settings, JSON logging, database bootstrap, and package layout | `feature/backend-config-logging` | — | F14 | not started |
| P1-2 | FastAPI lifespan, health routes, and request-ID middleware | `feature/backend-health-request-id` | P1-1 | N3 | not started |
| P1-3 | Offline pytest harness, `.env.example`, Make targets, and runtime checks | `feature/offline-test-harness` | P1-1, P1-2 | F14 | not started |

## Phase 2 — Persistence and demo data

| ID | Task | Branch | Depends on | Requirements | Status |
|---|---|---|---|---|---|
| P2-1 | SQLAlchemy entities and shared domain constants | `feature/sqlalchemy-entities` | P1-3 | F1, F4 | not started |
| P2-2 | PostgreSQL schema, RLS policies, seed SQL, and migration baseline | `feature/database-schema-rls` | P2-1 | F1, F4 | not started |
| P2-3 | Demo JSON/knowledge data and idempotent SQLite bootstrap | `feature/demo-data-bootstrap` | P2-1, P2-2 | F1, F4 | not started |

## Phase 3 — Identity and request guards

| ID | Task | Branch | Depends on | Requirements | Status |
|---|---|---|---|---|---|
| P3-1 | Supabase-compatible JWT authentication and demo tokens | `feature/jwt-auth-rbac` | P2-3 | N1 | not started |
| P3-2 | Role hierarchy and route dependencies | `feature/role-enforcement` | P3-1 | N1 | not started |
| P3-3 | Redis rate limiting, audit middleware, and middleware-order tests | `feature/request-guards-audit` | P3-1, P3-2 | N2, N6 | not started |

## Phase 4 — Support API

| ID | Task | Branch | Depends on | Requirements | Status |
|---|---|---|---|---|---|
| P4-1 | Repository/service layer for tickets and customer context | `feature/support-repositories-services` | P3-3 | F1, F4 | not started |
| P4-2 | Ticket create/list/detail API and schemas | `feature/api-tickets` | P4-1 | F1 | not started |
| P4-3 | Customer, subscription, workspace, and history API | `feature/api-customer-context` | P4-1 | F4 | not started |

## Phase 5 — Knowledge pipeline

| ID | Task | Branch | Depends on | Requirements | Status |
|---|---|---|---|---|---|
| P5-1 | Article loader and heading-aware 900/150 chunking | `feature/rag-ingest-chunking` | P2-3 | F5 | not started |
| P5-2 | In-memory/Qdrant vector-store protocol and BM25 index | `feature/rag-vector-stores` | P5-1 | F5 | not started |
| P5-3 | Hybrid retrieval, RRF, rerank, cache, and filters | `feature/rag-hybrid-retriever` | P5-2 | F5, F6 | not started |
| P5-4 | Knowledge search and admin reindex API | `feature/api-knowledge-reindex` | P3-3, P5-3 | F5 | not started |

## Phase 6 — Tools and policy

| ID | Task | Branch | Depends on | Requirements | Status |
|---|---|---|---|---|---|
| P6-1 | Tool policy, registry, timeout, and `ToolResult` behavior | `feature/tool-registry-policy` | P3-3, P4-1 | F9 | not started |
| P6-2 | Read and write tools through repository/service boundaries | `feature/support-tools` | P6-1 | F9 | not started |
| P6-3 | Integration protocols, mocks, and factory | `feature/mock-integrations` | P6-1 | F9, F14 | not started |

## Phase 7 — Rules and guardrails

| ID | Task | Branch | Depends on | Requirements | Status |
|---|---|---|---|---|---|
| P7-1 | Category, severity, escalation, and risk rules | `feature/deterministic-support-rules` | P2-3 | F3, F10 | not started |
| P7-2 | Injection scanning, untrusted wrapping, and security preamble | `feature/prompt-injection-guards` | P7-1 | N4 | not started |
| P7-3 | Customer-output validation and secret scrubbing | `feature/output-memory-guards` | P7-2 | N5, N7 | not started |

## Phase 8 — Specialist agents

| ID | Task | Branch | Depends on | Requirements | Status |
|---|---|---|---|---|---|
| P8-1 | LLM provider abstraction, fake provider, and structured-call telemetry | `feature/structured-llm-provider` | P1-3, P7-3 | F14 | not started |
| P8-2 | Workflow schemas plus supervisor and customer agents | `feature/supervisor-customer-agents` | P4-3, P8-1 | F2, F3, F4 | not started |
| P8-3 | Knowledge and troubleshooting agents | `feature/knowledge-troubleshooting-agents` | P5-3, P8-1 | F5, F6, F7 | not started |
| P8-4 | Resolution and escalation agents with deterministic actions | `feature/resolution-escalation-agents` | P6-3, P7-3, P8-1 | F8, F9, F10 | not started |

## Phase 9 — Workflow graph and trace

| ID | Task | Branch | Depends on | Requirements | Status |
|---|---|---|---|---|---|
| P9-1 | Support state, reducers, nodes, graph constants, and routing | `feature/langgraph-workflow` | P8-2, P8-3, P8-4 | F11 | not started |
| P9-2 | In-memory/SQLite checkpointer and workflow service | `feature/workflow-persistence` | P9-1 | F11 | not started |
| P9-3 | Workflow tracer, run/poll/events API, and low-risk end-to-end test | `feature/workflow-observability` | P9-2 | F13 | not started |

## Phase 10 — Approval and escalation

| ID | Task | Branch | Depends on | Requirements | Status |
|---|---|---|---|---|---|
| P10-1 | Human-approval interrupt, request persistence, and resume service | `feature/workflow-human-approval` | P9-3 | F9 | not started |
| P10-2 | Approve/reject routes, idempotent execution, and 409 behavior | `feature/api-approval-decisions` | P10-1 | F9 | not started |
| P10-3 | Policy escalation path and CD-1002/CD-1005/CD-1013 end-to-end tests | `feature/workflow-escalation-safety` | P10-2 | F9, F10, N4 | not started |

## Phase 11 — Memory

| ID | Task | Branch | Depends on | Requirements | Status |
|---|---|---|---|---|---|
| P11-1 | Short-term Redis/fakeredis conversation, state, and retrieval cache | `feature/short-term-memory` | P5-3, P9-3 | F4 | not started |
| P11-2 | Long-term customer-memory repository and scrubbed deduplication | `feature/long-term-memory` | P7-3, P11-1 | F11, N7 | not started |
| P11-3 | Recall and memory-update workflow integration | `feature/workflow-memory` | P10-3, P11-2 | F4, F11 | not started |

## Phase 12 — Agent console

| ID | Task | Branch | Depends on | Requirements | Status |
|---|---|---|---|---|---|
| P12-1 | Next.js shell, authentication, typed API client, and shared UI kit | `feature/frontend-foundation` | P4-3, P9-3 | F12 | not started |
| P12-2 | Dashboard, ticket/customer lists, knowledge, escalation, agents, audit, and settings pages | `feature/frontend-console-pages` | P12-1 | F12 | not started |
| P12-3 | Three-column ticket workflow, approval, reply, request-info, and role-aware controls | `feature/frontend-ticket-actions` | P10-3, P11-3, P12-2 | F12 | not started |
| P12-4 | Frontend component/API tests and browser acceptance pass | `feature/frontend-acceptance` | P12-3 | F12 | not started |

## Phase 13 — Evaluation and delivery

| ID | Task | Branch | Depends on | Requirements | Status |
|---|---|---|---|---|---|
| P13-1 | Evaluation dataset, metrics, and threshold tests | `feature/evaluation-quality-gates` | P10-3, P11-3 | F2, F5, F8, F10 | not started |
| P13-2 | Backend/frontend containers, Compose, health checks, and smoke test | `feature/container-delivery` | P12-4, P13-1 | N8 | not started |
| P13-3 | AWS/Azure/GCP Terraform roots, Kubernetes, and safe deployment scripts | `feature/multicloud-infrastructure` | P13-2 | N8 | not started |
| P13-4 | Test, security, image, Terraform, and reviewed deploy workflows | `feature/github-actions-delivery` | P13-2, P13-3 | N8 | not started |
| P13-5 | Final offline validation, demos, traceability, and honest-status update | `feature/final-validation` | P13-1, P13-2, P13-3, P13-4 | F1–F14, N1–N8 | not started |

## Tracker update rules

- `implemented` means the row's code and tests exist; it does not mean they passed.
- `validated locally` requires the row's tests and current phase checkpoint to pass on this machine.
- A phase is updated in `PLAN_PHASE.md` only when its exit criteria are satisfied.
- Update `MEMORY.md` whenever implementation, local validation, credentials, CI execution, or deployment state changes.
- A merge to `main` is not a deployment.

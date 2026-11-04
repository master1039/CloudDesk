# CloudDesk architecture

Architecture reference for the Autonomous Customer Support & Resolution Platform. `CLAUDE.md` remains authoritative. This document describes the target design; consult `MEMORY.md` for what is actually implemented or deployed.

## System context

CloudDesk is an internal support-agent console. Customers create tickets through mocked email, chat, web, or API channels; support staff inspect and control an AI-assisted resolution workflow. Consequential actions remain human-gated.

```mermaid
flowchart LR
    Customer[Customer channels<br/>email · chat · web · API] -->|ticket| API
    Agent[Support agent<br/>viewer · agent · admin] -->|HTTPS| UI[Next.js 15 console<br/>:3000]
    UI -->|REST /api/v1<br/>Bearer JWT + X-Request-ID| API[FastAPI<br/>:8000]
    API --> Services[Application services]
    Services --> Graph[LangGraph support workflow]
    Services --> Repos[Repositories]
    Graph --> Specialists[Six specialist agents]
    Graph --> Tools[ToolRegistry + ToolPolicy]
    Graph --> RAG[Hybrid RAG]
    Graph --> Memory[Memory facades]
    Repos --> SQL[(PostgreSQL / SQLite)]
    RAG --> Vector[(Qdrant / in-memory)]
    Memory --> Cache[(Redis / fakeredis)]
    Memory --> SQL
    Specialists --> LLM[LLM provider<br/>fake by default]
    Tools --> Mocks[Mock integrations]
```

## Runtime components

| Component | Responsibility | Boundary |
|---|---|---|
| Next.js console | Authentication UI, lists, ticket workspace, workflow polling, approval controls | Calls only `frontend/lib/api.ts`; never receives a service-role key |
| FastAPI API | HTTP validation, JWT/RBAC, middleware, background-task entrypoints | Contains no business policy |
| Services | Coordinate repositories, graph runs, approval resume, and seed operations | No HTTP concerns |
| Repositories | All SQLAlchemy persistence | No LLM or HTTP calls |
| LangGraph workflow | Execute and persist the ticket-resolution state machine | Nodes return partial state only |
| Specialist agents | Classification, context, knowledge, diagnosis, resolution, escalation | Structured outputs; no direct SQL |
| Rules and guardrails | Deterministic policy, injection defense, output validation, scrubbing | Rules override model judgment |
| Tool registry | Enforce allow-list, timeout, approval state, and uniform results | Every tool invocation passes through it |
| RAG | Load, chunk, index, retrieve, fuse, and rerank knowledge | Does not know ticket persistence |
| Memory | Short-term Redis and durable customer-note facades | Never stores secrets or raw ticket bodies |
| Integrations | Protocols and mock external services | Core does not import integrations |

## Dependency direction

```mermaid
flowchart TD
    Frontend --> API
    API --> Services
    Services --> Repositories
    Services --> Workflow
    Workflow --> Agents
    Workflow --> Tools
    Workflow --> RAG
    Workflow --> Memory
    Agents --> CoreLLM[Core LLM/guardrails/observability]
    Tools --> Repositories
    Tools --> Integrations
    RAG --> CoreConfig[Core configuration]
    Memory --> Repositories
    Memory --> CoreRedis[Core Redis]
```

Forbidden dependencies include repositories calling LLMs, agents writing SQL, API handlers containing policy, tools bypassing the registry, RAG importing ticket code, integrations imported by core, and frontend code holding backend secrets.

## Secret-scrubbing boundary

`backend.app.core.guardrails.scrub` is the deterministic N7 boundary for text that may later enter
durable memory. It reuses the same centralized secret patterns as customer-output validation, checks
payment-card candidates with Luhn, and removes complete private-key blocks and credential-bearing
URLs. Matches are collected against the original input, overlapping spans are merged, and each span
is replaced with the generic `[REDACTED]` marker. This keeps replacement stable and idempotent without
returning or logging the matched secret. Future memory writers must call `scrub` before persistence.

## Tool execution boundary

`ToolPolicy` classifies every known capability before execution. Read-only lookups, routine ticket
updates, and the safe escalation path do not need approval; refund requests and workspace-setting
resets do. Unclassified registered extensions default to approval-required, while unregistered names
never execute. `ToolRegistry.execute(name, args, approved=...)` is the shared automatic and
human-approved path. It accepts only asynchronous LangChain `@tool` definitions, enforces
`TOOL_TIMEOUT_SECONDS`, and converts timeouts or exceptions into scrubbed `ToolResult` values so a
tool adapter cannot crash the workflow.

P6-2 registers five read-only capabilities through a dependency-injected factory. Customer and
subscription lookups expose safe projections, ticket history is capped at ten and omits bodies and
messages, document search reuses the cited hybrid retriever, and service status uses a replaceable
`ServiceStatusProvider`. The repository-backed provider can read seeded incidents without changing
tool names, policy, or execution flow.

P6-3 adds four write capabilities on the same boundary. `update_ticket` limits routine mutations to
status, category, severity, and summary. `create_escalation` transactionally creates the safe fallback,
marks the ticket escalated, and reuses an identical open escalation. Refund requests and demo-setting
resets delegate to injected provider protocols only after `ToolRegistry.execute(..., approved=True)`
passes policy. Money uses `Decimal`, and refund calls require an idempotency key.

P6-4 implements those protocols with deterministic, stateful in-memory mocks. Refund requests use
stable IDs and reject conflicting idempotency-key reuse while explicitly reporting that no money was
moved. Workspace changes remain in process and report that no external account changed. Service
status loads validated checked-in incidents. `create_integrations` selects this provider set only in
demo mode and otherwise fails closed; `create_support_tool_registry` composes all nine tools around
one provider set and one `ToolRegistry` execution boundary.

## Deterministic escalation and severity policy

P7-1 places model-independent safety policy in `agents/rules.py`. One ordered immutable rule table
covers security incidents, data loss, account deletion, payment disputes, explicit legal requests,
and enterprise-wide outages. Every rule names its destination team, explanation, and minimum
severity. `matching_escalation_rules` returns all policy evidence in stable routing order, while
`policy_escalation` uses the first match for ownership and the highest matched severity for priority.
`rule_severity` can raise a model assessment to that deterministic minimum but can never lower it.
This keeps mandatory routing explainable and leaves only unmatched grey areas for later model
judgement.

## Ticket workflow

```mermaid
flowchart TD
    A[understand_ticket] --> B[classify_severity]
    B --> C[customer_context]
    C --> D[knowledge_retrieval]
    D --> E[troubleshooting]
    E --> F[resolution_planning]
    F --> G[risk_check]
    G -->|policy escalation| H[escalation]
    G -->|approval required| I[human_approval]
    G -->|low risk| J[execute_resolution]
    I -->|approved| J
    I -->|rejected| H
    H --> K[ticket_summary]
    J --> K
    K --> L[memory_update]
    L --> M((END))
```

The graph persists state after every node. `errors` and `completed_nodes` append through reducers. Code before `interrupt()` must be small and idempotent because it runs again on resume.

## Run and approval sequence

```mermaid
sequenceDiagram
    actor A as Support agent
    participant UI as Next.js
    participant API as FastAPI
    participant S as Workflow service
    participant G as LangGraph
    participant DB as SQL/checkpointer

    A->>UI: Run workflow
    UI->>API: POST /tickets/{id}/run
    API->>S: create_run()
    S->>DB: Insert workflow_run
    API-->>UI: 202 {workflow_id}
    S->>G: start_workflow(state)
    loop after every node
        G->>DB: Save state and workflow events
        UI->>API: GET /tickets/{id}/workflow
        API-->>UI: Current progress
    end
    G->>G: interrupt() at human_approval
    S->>DB: Create approval; ticket = waiting_on_approval
    A->>UI: Approve or reject
    UI->>API: POST /approvals/{id}/approve or /reject
    API->>G: Command(resume=decision)
    G->>DB: Execute or escalate, summarize, update memory
```

## Data and state

Primary tables are `profiles`, `customers`, `subscriptions`, `workspaces`, `products`, `tickets`, `ticket_messages`, `support_articles`, `incidents`, `workflow_runs`, `workflow_events`, `resolution_actions`, `approval_requests`, `escalations`, `customer_memory`, and `audit_logs`.

- SQLAlchemy uses portable JSON and `String(36)` UUIDs for SQLite/PostgreSQL parity.
- PostgreSQL DDL and RLS live under `database/`; `database/schema.sql` becomes authoritative once implemented.
- Workflow state is persisted in `workflow_runs.state`; node/tool/model history is append-only in `workflow_events`.
- Short-term ticket state and retrieval caching live in Redis/fakeredis.
- Knowledge vectors live in Qdrant or the in-memory implementation behind `VectorStoreService`.

P8-1 places short-term conversation and workflow context behind `memory.ShortTermMemory`. Conversation
messages are appended in order to ticket-scoped Redis lists, while the latest workflow snapshot is a
ticket-scoped JSON string. Every write applies or refreshes a 24-hour TTL. The facade validates ticket
identifiers before constructing keys, tolerates malformed ephemeral entries without crossing ticket
boundaries, supports explicit per-ticket cleanup, and accepts the shared Redis client or fakeredis by
dependency injection.

## Security boundaries

- Bearer JWT establishes identity; `require_role` enforces `viewer < agent < admin`.
- Request-ID, rate-limit, and audit middleware apply to API traffic; every non-GET request is audited.
- Customer-controlled content is scanned by deterministic N4 patterns before model use. The scanner
  normalizes Unicode and zero-width obfuscation and returns stable signal names for auditability.
- `wrap_untrusted` XML-escapes content and source labels inside one `<untrusted_content>` block, so
  injected closing tags cannot escape the data boundary. Every future specialist prompt shares
  `SECURITY_PREAMBLE`, which forbids obeying embedded instructions, revealing prompts or secrets,
  invoking tools, or changing workflow routing because customer-controlled text asks.
- Customer-facing output receives a structured validation result before display. Empty output,
  internal/private URLs, secret classes, and explicitly supplied other-customer identifiers produce
  generic violation codes without echoing matched data; every failure is invalid and `high` risk.
  Public documentation links and identifiers belonging to the current customer remain allowed.
- Refunds, deletions, disputes, and workspace-setting changes cannot execute without the defined approval/escalation policy.
- Secrets are server-side environment values only and never enter logs, prompts exposed to operators, memory notes, frontend bundles, or Git.

## Deployment topology

```mermaid
flowchart LR
    Internet --> LB[Managed load balancer]
    LB --> FE[Frontend container]
    FE --> BE[Backend container]
    BE --> PG[(Supabase/PostgreSQL)]
    BE --> Redis[(Managed Redis)]
    BE --> Qdrant[(Qdrant Cloud)]
    BE --> Provider[LLM API]
    BE --> Logs[Cloud logs/metrics]
    Secrets[Cloud secret manager] --> FE
    Secrets --> BE
```

AWS maps to ECR/ECS Fargate/ALB/Secrets Manager/CloudWatch; Azure maps to ACR/Container Apps/Key Vault/Log Analytics; GCP maps to Artifact Registry/Cloud Run/Secret Manager/Cloud Logging. Terraform files describe deployability; only `MEMORY.md` may record whether any environment was actually applied.

## Observability

Every log line carries `request_id` and, when relevant, `workflow_id`. `WorkflowTracer` records node start/completion, tool calls, model calls, approval events, errors, and completion, including duration, token usage, and estimated cost. Telemetry failures never fail the workflow. Raw prompts, hidden reasoning, secrets, and cross-customer data are never exposed.


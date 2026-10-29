# CloudDesk API contract

Target HTTP contract for the v1 agent console. This document is authoritative for routes and transport types once implementation begins; `CLAUDE.md` remains authoritative for product behavior and policy. Current implementation status is tracked in `MEMORY.md`.

## Conventions

- Base path: `/api/v1`, except health routes.
- Content type: `application/json`.
- Authentication: `Authorization: Bearer <JWT>` unless a route is marked public.
- Every response includes `X-Request-ID`; callers may provide one.
- IDs are UUID strings unless a display ID such as `CD-1002` is explicitly named.
- Timestamps are UTC ISO 8601 strings.
- Errors use `{ "detail": string }`.
- List responses use `{ "items": T[], "total": integer, "limit": integer, "offset": integer }`.
- Unknown resources return 404; invalid input returns 422; insufficient role returns 403.
- Non-health HTTP requests use a per-client, 60-second Redis fixed window. Responses include
  `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and the Unix timestamp `X-RateLimit-Reset`. A blocked
  request returns `429 { "detail": "Rate limit exceeded" }` plus `Retry-After`. Health routes and CORS
  preflight requests are exempt; unavailable Redis returns 503 rather than silently disabling limits.
- A second run while a ticket waits for approval returns 409. Resuming a non-paused run returns 409.

Roles: `viewer` can read; `agent` can run workflows and act on tickets/approvals; `admin` additionally manages knowledge indexing and settings.

## Shared enums

```text
Role = viewer | agent | admin
TicketCategory = login_issue | billing | api_failure | workspace_permissions |
                 storage_quota | integration | feature_request | account | security | other
TicketStatus = new | in_progress | waiting_on_customer | waiting_on_approval |
               escalated | resolved | closed
Severity = low | medium | high | critical
Channel = email | chat | web | api
WorkflowStatus = queued | running | waiting_on_approval | completed | failed
ApprovalStatus = pending | approved | rejected
```

## Health

| Method | Path | Auth | Response |
|---|---|---|---|
| GET | `/health` | public | `200 HealthResponse` |
| GET | `/health/live` | public | `200 {"status":"ok"}` with no dependency I/O |
| GET | `/health/ready` | public | `200` when dependencies are ready; `503` otherwise |

`GET /health` returns `HealthResponse`: `status: "ok"` and `version`.

`GET /health/live` returns only `{ "status": "ok" }` and performs no dependency I/O.

`GET /health/ready` returns `status`, `version`, and `dependencies`, a string map populated as
database, Redis, vector-store, and LLM readiness checks are introduced. It is empty during the
runtime-skeleton phase.

## Authentication

Bearer tokens use HS256, require `sub` and `exp`, and are verified with
`SUPABASE_JWT_SECRET` when configured or `JWT_SECRET` otherwise. CloudDesk roles may be carried in
`app_role`, `app_metadata.role`, `user_metadata.role`, or a top-level `role`; only `viewer`, `agent`,
and `admin` are accepted as application roles. A Supabase `aud: authenticated` claim is supported.
Missing or invalid credentials return 401, while an authenticated user below the route's minimum
role receives 403.

| Method | Path | Role | Request | Response |
|---|---|---|---|---|
| POST | `/api/v1/auth/login` | public | `LoginRequest` | `200 AuthResponse` |
| GET | `/api/v1/auth/me` | viewer | — | `200 Profile` |

`LoginRequest`: `email`, `password`. In demo mode this authenticates only configured demo users.
All three checked-in demo profiles use the intentionally public password `clouddesk-demo`; local login
returns 403 when `DEMO_MODE=false`. Invalid email and password attempts share the same 401 response.

`AuthResponse`: `access_token`, `token_type: "bearer"`, `expires_in`, `user: Profile`. Demo tokens
expire after 8 hours (`expires_in: 28800`).

`Profile`: `id`, `email`, `display_name`, `role`.

## Dashboard

| Method | Path | Role | Response |
|---|---|---|---|
| GET | `/api/v1/dashboard/summary` | viewer | `200 DashboardSummary` |

`DashboardSummary`: ticket counts by status and severity, pending approval count, open escalation count, median time-to-first-response, and recent ticket summaries. Metrics are observations, not hard-coded targets.

## Tickets

| Method | Path | Role | Result |
|---|---|---|---|
| GET | `/api/v1/tickets` | viewer | Paginated `TicketSummary` list |
| POST | `/api/v1/tickets` | agent | `201 TicketDetail` |
| GET | `/api/v1/tickets/{ticket_id}` | viewer | `200 TicketDetail` |
| POST | `/api/v1/tickets/{ticket_id}/run` | agent | `202 {"workflow_id": string}` |
| GET | `/api/v1/tickets/{ticket_id}/workflow` | viewer | `200 WorkflowView` |
| GET | `/api/v1/tickets/{ticket_id}/events` | viewer | Paginated `WorkflowEvent` list |
| POST | `/api/v1/tickets/{ticket_id}/reply` | agent | `200 TicketMessage` |
| POST | `/api/v1/tickets/{ticket_id}/request-info` | agent | `200 TicketMessage` |
| POST | `/api/v1/tickets/{ticket_id}/escalate` | agent | `201 Escalation` |

P4 implements the first three routes in this table. The workflow and action routes remain the
forward contract for their later phases. `{ticket_id}` is the internal UUID; `display_id` is returned
for human-facing values such as `CD-1002`.

`TicketListParams` defines optional filters `status`, `severity`, `category`, `channel`, `customer_id`,
and `search`. Pagination uses
`limit` (default 50, minimum 1, maximum 100) and `offset` (default 0, minimum 0). `search` matches the
display ID, subject, or customer name. Results are ordered by newest creation time, then ID. Invalid
enum filters return 422.

`CreateTicketRequest`:

```json
{
  "customer_id": "uuid",
  "subject": "Unable to sign in",
  "body": "Customer-provided text",
  "channel": "email"
}
```

`CreateTicketRequest` trims all text fields. `customer_id`, `subject`, and `body` cannot be blank;
`subject` is limited to 500 characters and `body` to 50,000. `channel` accepts exactly `email`,
`chat`, `web`, or `api` (F1). An unknown customer returns 404. Creation returns a new ticket with
status `new`; category, severity, and summary are null until classification.

`TicketSummary`: `id`, `display_id`, `subject`, `customer_id`, `customer_name`, `channel`, `status`,
nullable `category`, nullable `severity`, nullable `summary`, `created_at`, `updated_at`.

`TicketDetail` extends `TicketSummary` with:

- `body` and `messages: TicketMessage[]`;
- nullable `workflow: WorkflowReference`, `approval: ApprovalReference`, and
  `escalation: EscalationReference`;
- `customer_context_links: CustomerContextLinks`.

`WorkflowReference`: `id`, `status`, `url`.

`ApprovalReference`: `id`, `status`, `url`.

`EscalationReference`: `id`, `status`, `team`, `url`.

`CustomerContextLinks`: `customer`, nullable `subscription`, nullable `workspace`, and
`previous_tickets`. Each value is an API-relative URL. Links avoid copying the full customer account
graph into every ticket response. Ticket subject and body are always untrusted data.

`TicketMessage`: `id`, `ticket_id`, `direction` (`inbound|outbound|internal`), `author`, `body`, `created_at`.

`ReplyRequest`: `body`. The server validates output before recording an outbound message.

`RequestInfoRequest`: `body`, containing the approved question to send through the mock integration.

`EscalateTicketRequest`: `team`, `reason`, optional `priority`.

## Workflow view

`WorkflowView` contains:

- `id`, `ticket_id`, `status`, `current_node`, `completed_nodes`, `started_at`, `updated_at`, nullable `completed_at`.
- nullable `classification`, `severity_assessment`, `customer_context`, `evidence`, `previous_cases`, `diagnosis`, `resolution_plan`, `risk`, `escalation`, and `approval`.
- `token_usage`, `estimated_cost`, and scrubbed `errors`.

`Evidence`: `id`, `title`, `source`, `snippet`, `score`, `url`, `article_id`.

`Diagnosis`: `probable_causes`, numbered `steps`, `confidence`, and optional service-status context.

`ResolutionPlan`: `summary`, `customer_reply`, `internal_notes`, and deterministic `actions`.

`PlannedAction`: `tool`, `arguments`, `requires_approval`, `reason`, and current execution status. Arguments exposed to the UI must be scrubbed.

`WorkflowEvent`: `id`, `workflow_id`, `event_type`, `node`, `duration_ms`, `token_usage`, `estimated_cost`, scrubbed `input_summary`, scrubbed `output_summary`, `created_at`. It never includes raw prompts or hidden reasoning.

## Approvals

| Method | Path | Role | Request | Result |
|---|---|---|---|---|
| GET | `/api/v1/approvals` | viewer | — | Paginated `ApprovalRequest` list |
| GET | `/api/v1/approvals/{approval_id}` | viewer | — | `200 ApprovalRequest` |
| POST | `/api/v1/approvals/{approval_id}/approve` | agent | `ApprovalDecisionRequest` | `202 ApprovalRequest` |
| POST | `/api/v1/approvals/{approval_id}/reject` | agent | `ApprovalDecisionRequest` | `202 ApprovalRequest` |

`ApprovalRequest`: `id`, `ticket_id`, `workflow_id`, `action`, scrubbed `arguments`, `reason`, `status`, `requested_at`, nullable `decided_at`, nullable `decided_by`, nullable `decision_note`.

`ApprovalDecisionRequest`: optional `note`. Decisions are idempotent; a conflicting second decision returns 409.

## Customers

| Method | Path | Role | Result |
|---|---|---|---|
| GET | `/api/v1/customers` | viewer | Paginated `CustomerSummary` list |
| GET | `/api/v1/customers/{customer_id}` | viewer | `200 CustomerDetail` |

`CustomerListParams` defines optional `search` and `plan`, plus the shared `limit` and `offset` rules. `search`
matches customer name, email, or company. Results are ordered by customer name, then ID.

`CustomerSummary`: `id`, `name`, `email`, nullable `company`, nullable `plan`, nullable
`workspace_id`, `created_at`.

`CustomerDetail` extends `CustomerSummary` with nullable `subscription: Subscription`, nullable
`workspace: Workspace`, `previous_tickets: TicketSummary[]`, and
`memory_notes: CustomerMemoryNote[]`. Previous tickets are newest first and limited to 10. Memory
notes are scrubbed, newest first, and limited to 10 (F4).

`Subscription`: `id`, `plan`, `status`, `seats`, `amount` (decimal string), `currency`,
`billing_interval`, nullable `current_period_end`.

`Workspace`: `id`, `name`, `slug`, `storage_used_bytes`, `storage_limit_bytes`.

`CustomerMemoryNote`: `id`, `memory_type`, `content`, nullable `source_ticket_id`, `created_at`.
The response never includes memory fingerprints, internal attributes, or raw ticket bodies.

## Knowledge

| Method | Path | Role | Request/Query | Result |
|---|---|---|---|---|
| GET | `/api/v1/knowledge` | viewer | pagination/category/search | Article summaries |
| GET | `/api/v1/knowledge/{article_id}` | viewer | — | `200 KnowledgeArticle` |
| POST | `/api/v1/knowledge/search` | viewer | `KnowledgeSearchRequest` | `200 {"items": Evidence[]}` |
| POST | `/api/v1/knowledge/reindex` | admin | optional provider/model override | `202 ReindexJob` |

`KnowledgeSearchRequest`: `query`, optional `category`, `mode` (`hybrid|semantic|keyword`, default `hybrid`), and `top_k`.

`KnowledgeArticle`: `id`, `slug`, `title`, `category`, `tags`, `summary`, `body`, `updated_at`.

`ReindexJob`: `id`, `status`, `collection`, `created_at`. Reindex recreates the selected collection.

## Escalations

| Method | Path | Role | Result |
|---|---|---|---|
| GET | `/api/v1/escalations` | viewer | Paginated `Escalation` list |
| GET | `/api/v1/escalations/{escalation_id}` | viewer | `200 Escalation` |

`Escalation`: `id`, `ticket_id`, `workflow_id`, `team`, `reason`, `policy_rules`, `status`, `created_at`, nullable `resolved_at`.

## Agent graph

| Method | Path | Role | Result |
|---|---|---|---|
| GET | `/api/v1/agents` | viewer | `200 AgentGraph` |

`AgentGraph`: `nodes` from `GRAPH_NODES`, `edges` from `GRAPH_EDGES`, and specialist metadata safe for operators. It does not expose prompts.

## Audit

| Method | Path | Role | Result |
|---|---|---|---|
| GET | `/api/v1/audit` | viewer | Paginated `AuditEntry` list |

Filters: `actor_id`, `method`, `path`, `request_id`, `from`, `to`, `limit`, `offset`.

`AuditEntry`: `id`, `actor_id`, `actor_role`, `method`, `path`, `status_code`, `request_id`, scrubbed `change_summary`, `created_at`.

Every non-GET request is audited, including rejected requests. Audit middleware never stores request
bodies, authorization headers, query values, passwords, or tokens. `change_summary` contains only the
outcome class and whether a valid bearer identity was present. Audit persistence failures are logged
without replacing the HTTP response already produced for the caller.

## Settings

| Method | Path | Role | Result |
|---|---|---|---|
| GET | `/api/v1/settings` | admin | `200 PublicSettings` |
| PATCH | `/api/v1/settings` | admin | `200 PublicSettings` |

Only non-secret operational settings may be returned or changed. Provider API keys, JWT secrets, service-role keys, database credentials, and cloud credentials are never represented in this API.

## MCP tools

| Method | Path | Role | Result |
|---|---|---|---|
| GET | `/api/v1/mcp/tools` | viewer | Read-only tool descriptors |

The v1 MCP surface exposes read-only tools only. Descriptors include name, description, and JSON schema; execution still follows the same authorization and registry policy.

## Contract-change rule

Every implemented contract change updates this file, `backend/app/schemas/`, and `frontend/lib/types.ts` in the same change. Add tests for status code, role enforcement, input validation, response shape, and relevant requirement IDs.

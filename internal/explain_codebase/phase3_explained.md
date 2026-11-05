# Phase 3 Explained: Identity, Access Control, Rate Limiting, and Audit

## The simple summary

In Phase 3, I added the security guards around CloudDesk. The system can now identify a support employee, decide what that person is allowed to do, slow down excessive traffic, give demo users temporary login tokens, and record every state-changing request without storing sensitive request content.

If the earlier phases built the office and filing system, Phase 3 added the reception desk, employee badges, access levels, crowd control, and security logbook.

## The four questions Phase 3 answers

Every protected request now has to answer four simple questions:

1. Who is making this request?
2. Does that person have enough permission?
3. Is this client sending too many requests?
4. If the request may change data, what happened and how can it be traced?

Each question is handled by a separate component. This keeps security logic reusable instead of copying it into every future endpoint.

## Identity through signed tokens

CloudDesk uses a JSON Web Token, commonly called a JWT. A JWT is similar to a temporary signed employee badge.

The badge contains information such as:

- the employee’s unique ID;
- email and display name;
- role;
- issue time;
- and expiration time.

The server signs the token with an HS256 secret. When the token returns with a request, the server verifies the signature and expiration before trusting it. A caller cannot safely change “viewer” to “admin,” because changing the contents invalidates the signature.

The validator requires both a subject, meaning the user ID, and an expiration time. It rejects missing, malformed, expired, incorrectly signed, and role-less tokens with a standard 401 response.

The token shape is compatible with the Supabase authentication style. CloudDesk can read application roles from normal claims or Supabase metadata. When a Supabase JWT secret is configured, it takes priority over the local secret.

If no signing secret is configured, authentication fails closed with a service-unavailable response. It does not silently allow access.

## Role-based access control

CloudDesk has three support roles:

- A `viewer` may read support information.
- An `agent` may do everything a viewer can do and may also run workflows, reply, approve or reject, and escalate.
- An `admin` may do everything an agent can do and may also manage higher-level operations such as settings and knowledge reindexing.

The hierarchy is:

`viewer < agent < admin`

Routes use one reusable `require_role` rule. A route can say, “agent or higher required,” rather than manually checking every role.

If a person is correctly authenticated but lacks permission, CloudDesk returns 403. This distinction matters:

- 401 means, “I cannot verify who you are.”
- 403 means, “I know who you are, but you are not allowed to do this.”

## Demo login and temporary tokens

The project includes three fictional demo support users: one viewer, one agent, and one administrator.

The public demo login credential is intentionally limited to demo mode. Outside demo mode, the local login route is disabled.

The login flow is:

`Email and demo password → find active seeded profile → verify credential → issue signed token`

Unknown users and incorrect passwords receive the same generic response. This avoids revealing whether an email address exists.

Demo tokens expire after eight hours. The `/api/v1/auth/me` endpoint verifies the token and then checks the current database profile. This means an old token cannot make an inactive or changed profile appear current.

Only public profile information and the bearer token are returned. Database credentials, JWT signing secrets, and service-role keys are never returned to the browser.

## Redis-backed rate limiting

Authentication protects identity, but a valid or anonymous client could still send excessive traffic. CloudDesk therefore applies a fixed-window rate limit.

The default demo limit is 120 requests per minute for each client IP address.

Redis stores a small counter for each client and minute. The process is:

`Request arrives → identify client IP → increment current minute counter → allow or reject`

Responses include:

- the request limit;
- the remaining count;
- and the time when the window resets.

When the limit is exceeded, the caller receives status 429 and a `Retry-After` value.

Health checks and browser preflight requests are exempt. Health monitoring should not fail because ordinary API traffic has reached its limit.

Local development and tests use fakeredis, an in-memory replacement with Redis behavior. A real deployment can use a Redis URL without changing the middleware logic.

If Redis is unavailable, CloudDesk returns 503 instead of quietly turning off the security control. This is a fail-closed choice: the system prefers a visible temporary failure over silently accepting unlimited traffic.

## Durable audit records

Every non-GET request is audited, including requests that are rejected. This covers actions that may change state, such as login attempts, future ticket updates, approvals, replies, and escalations.

An audit record stores:

- the known actor ID and role, when available;
- HTTP method and path;
- final status code;
- request ID;
- client IP and user-agent;
- and a small outcome summary.

The middleware deliberately does not store:

- request bodies;
- query values;
- passwords;
- authorization headers;
- or tokens.

For example, if a request contains a password or an API key, the audit row records that a request succeeded or failed, but it does not copy those sensitive values.

Audit storage occurs in its own database transaction after the response is produced. If audit persistence fails, the failure is logged but does not replace the response the caller already earned. This keeps observability from breaking normal application behavior.

## Middleware order in plain language

Middleware is a set of reusable layers around the application. The registered order is:

`CORS → Request ID → Rate Limit → Audit`

The framework wraps these layers like an onion, so the last registered layer is outermost. A request therefore enters through Audit, then Rate Limit, then Request ID, then CORS, before reaching the route. The response travels back through the layers in reverse.

This arrangement has useful consequences:

- Audit can observe successful and rejected state-changing requests.
- Rate Limit can stop excessive traffic before business code runs.
- Request IDs connect accepted requests to logs and audit rows.
- Early rate-limit responses create their own request ID so they remain traceable even when they stop before the normal request-ID layer.
- CORS controls how browser-based callers receive approved responses.

The registration order is covered by an automated test so a future refactor cannot accidentally rearrange the security behavior.

## Example: an agent changes something

A normal protected change follows this story:

1. The audit layer begins observing the request.
2. The rate limiter checks the client’s current minute counter.
3. A request ID is assigned.
4. The route validates the bearer token.
5. The role rule confirms that the user is an agent or administrator.
6. The route performs its work.
7. The response returns with request and rate-limit headers.
8. A scrubbed audit record is written with the same request ID.

If a viewer tries the same action, the route returns 403 and the rejected attempt is still audited.

## How I proved it works

The tests verify that:

- missing, malformed, expired, incorrectly signed, and incomplete tokens are rejected;
- viewer, agent, and administrator permissions follow the hierarchy;
- a viewer receives 403 on a mutating route;
- all three demo users can log in and receive eight-hour tokens;
- demo login is disabled outside demo mode;
- rate limits count, block, reset, and remain separate by client IP;
- health and preflight requests are exempt;
- rate-limit responses preserve request IDs;
- successful and rejected mutations create audit rows;
- GET requests do not create audit rows;
- secrets and query values do not enter audit summaries;
- audit failure does not replace a successful response;
- and the middleware registration order is exact.

The integrated Phases 1 through 3 suite currently passes 67 tests entirely offline.

## What Phase 3 does not claim

The project used fakeredis and local signed demo tokens for validation. It did not connect to a live Redis server or Supabase account, and no cloud credentials were used.

Phase 3 provides reusable security controls. The full ticket and customer API, AI workflow, frontend console, containers, continuous integration, and cloud deployment are later phases.

## Closing explanation

The result of Phase 3 is a clear security boundary around the application. CloudDesk can identify users, enforce their role, control request volume, trace every response, and keep a privacy-conscious audit history. These controls are built before the main support APIs, so future features begin protected rather than adding security as an afterthought.

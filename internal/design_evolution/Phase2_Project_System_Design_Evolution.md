# Phase 2 — Project System Design Evolution

## Purpose and phase boundary

Phase 2 evolves the Phase 1 runtime into a data-backed support platform. It defines what CloudDesk stores, how application code accesses it, how PostgreSQL should protect it, and how a complete local demonstration is created.

The phase evolved through four subtasks:

1. P2-1 — SQLAlchemy entities and category enum
2. P2-2 — PostgreSQL schema, row-level security, and migrations
3. P2-3 — repository layer
4. P2-4 — sample data and demo bootstrap

## Beginning of Phase 2 — runtime without business memory

Phase 2 inherits the settings, logging, middleware, health routes, and tests from Phase 1. The API can run reliably, but it cannot remember a customer or ticket after a request finishes.

```mermaid
flowchart LR
    Caller["API caller"] --> Runtime["Phase 1 FastAPI runtime"]
    Runtime --> Health["Health response"]
    Runtime -. "no persistent business data yet" .-> Missing["Customers, tickets, knowledge, workflows"]
```

## P2-1 — Domain model and portable entities

### Design change

SQLAlchemy entities define the application's shared data language. Sixteen tables cover five related areas:

- accounts: profiles, workspaces, products, subscriptions;
- customers: customers and customer memory;
- support: tickets, ticket messages, support articles, and incidents;
- workflow: workflow runs, workflow events, resolution actions, approval requests, and escalations;
- governance: audit logs.

Portable IDs and JSON fields allow the same model to run with SQLite during offline tests and PostgreSQL in the intended production environment. A category enum gives ticket classification a controlled vocabulary.

```mermaid
flowchart TB
    App["FastAPI application"] --> ORM["SQLAlchemy entity model"]
    ORM --> Identity["Profiles, workspaces, products, subscriptions"]
    ORM --> Customer["Customers and customer memory"]
    ORM --> Support["Tickets, messages, articles, incidents"]
    ORM --> Workflow["Runs, events, actions, approvals, escalations"]
    ORM --> Governance["Audit logs"]
    ORM --> SQLite["SQLite for offline validation"]
    ORM -. "portable target" .-> Postgres["PostgreSQL"]
```

### Core relationship view

```mermaid
erDiagram
    PROFILES ||--o{ TICKETS : assigned_to
    WORKSPACES ||--o{ SUBSCRIPTIONS : owns
    PRODUCTS ||--o{ SUBSCRIPTIONS : selected_as
    CUSTOMERS ||--o{ TICKETS : opens
    CUSTOMERS ||--o{ CUSTOMER_MEMORY : has
    TICKETS ||--o{ TICKET_MESSAGES : contains
    TICKETS ||--o{ WORKFLOW_RUNS : processed_by
    WORKFLOW_RUNS ||--o{ WORKFLOW_EVENTS : records
    WORKFLOW_RUNS ||--o{ RESOLUTION_ACTIONS : proposes
    WORKFLOW_RUNS ||--o{ APPROVAL_REQUESTS : requests
    WORKFLOW_RUNS ||--o{ ESCALATIONS : raises
```

### Why the design improved

Later features can share one domain model instead of inventing incompatible data shapes. The model records both support data and the future automation trace needed to explain decisions.

## P2-2 — PostgreSQL schema, migration, and data boundary

### Design change

The conceptual model becomes a deployable PostgreSQL design:

- `database/schema.sql` defines the database objects;
- `database/migrations/0001_initial_schema.sql` gives the schema a repeatable starting migration;
- `database/rls_policies.sql` enables row-level security on every application table;
- authenticated access is read-oriented, while service-role code owns mutations.

The application also gains an asynchronous database engine and session factory. SQLite remains the local test database; `asyncpg` is the PostgreSQL path.

```mermaid
flowchart TB
    subgraph Application["Application process"]
        App["FastAPI runtime"] --> Session["Async database session"]
        Session --> ORM["SQLAlchemy entities"]
    end

    subgraph DatabaseAssets["Version-controlled PostgreSQL contract"]
        Migration["Initial migration"] --> Schema["16-table schema"]
        Schema --> RLS["Row-level security policies"]
    end

    ORM --> SQLite["SQLite\noffline tests"]
    ORM -. "intended runtime path" .-> PostgreSQL["PostgreSQL"]
    RLS --> PostgreSQL
    Authenticated["Authenticated role"] --> ReadPolicy["Read policies"] --> PostgreSQL
    ServiceRole["Service role"] --> MutationPolicy["Controlled writes"] --> PostgreSQL
```

### Why the design improved

Schema creation is reproducible, access rules live beside the code, and application I/O is asynchronous. Row-level security provides a database-side guard rather than relying only on route code.

## P2-3 — Repository layer separates storage from behavior

### Design change

Repositories become the only normal path through which services query and change domain data. They are grouped by responsibility: accounts, customers, tickets, knowledge, workflows, and audit.

Repositories perform data operations but do not decide when a business operation should be committed. The service layer owns transaction boundaries, including commit and rollback.

```mermaid
flowchart LR
    Route["API route"] --> Service["Service or use-case logic"]
    Service --> Accounts["Accounts repository"]
    Service --> Customers["Customers repository"]
    Service --> Tickets["Tickets repository"]
    Service --> Knowledge["Knowledge repository"]
    Service --> Workflows["Workflows repository"]
    Service --> Audit["Audit repository"]
    Accounts --> Session["Async DB session"]
    Customers --> Session
    Tickets --> Session
    Knowledge --> Session
    Workflows --> Session
    Audit --> Session
    Session --> Database["SQLite or PostgreSQL"]
    Service -. "commit or rollback" .-> Session
```

### Why the design improved

Routes do not need to know SQL details, repository queries can be tested independently, and one service can coordinate several repositories within one transaction.

## P2-4 — Repeatable demo world and startup lifecycle

### Design change

The final subtask creates a useful local system rather than an empty schema. Demo bootstrap data includes three user profiles, eight customers, thirteen tickets, fifteen knowledge articles, four memory records, and the supporting products, workspaces, subscriptions, messages, and incidents.

At application startup, the lifespan handler creates local tables and seeds demo data only when the configured demo database is empty. The operation is idempotent, so restarting the application does not multiply the sample records. A `make seed` command and SQL seed asset provide explicit setup paths.

```mermaid
flowchart TB
    Start["Application starts"] --> Lifespan["FastAPI lifespan"]
    Lifespan --> Create["Create local tables if needed"]
    Create --> Check{"Demo data already present?"}
    Check -- "yes" --> Serve["Start serving requests"]
    Check -- "no" --> Seed["Run demo seed service"]
    Seed --> Profiles["Profiles and accounts"]
    Seed --> Customers["Customers and memory"]
    Seed --> Support["Tickets, messages, articles, incidents"]
    Profiles --> Serve
    Customers --> Serve
    Support --> Serve
    Developer["Developer"] --> MakeSeed["make seed"] --> Seed
```

### Why the design improved

Every developer can start from the same meaningful scenario. Idempotency makes startup predictable, and the seed layer uses the same application abstractions instead of becoming a separate data model.

## End of Phase 2 — final persistence architecture

```mermaid
flowchart TB
    Caller["API caller"] --> Middleware["Phase 1 middleware"] --> Route["FastAPI route"]
    Env["Environment settings"] --> Runtime["Application runtime"]
    Runtime --> Route

    subgraph BusinessDataPath["Business data path"]
        Route --> Service["Service layer\ntransaction owner"]
        Service --> Repository["Domain repositories"]
        Repository --> Session["Async SQLAlchemy session"]
        Session --> Entities["16 shared entities"]
    end

    Entities --> SQLite["SQLite\noffline tests and local demo"]
    Entities -. "production database target" .-> PostgreSQL["PostgreSQL"]
    RLS["RLS policies"] --> PostgreSQL
    Migration["Schema and migration assets"] --> PostgreSQL

    Lifespan["Startup lifespan"] --> Bootstrap["Idempotent demo bootstrap"]
    Bootstrap --> Repository
    Tests["Offline pytest suite"] --> Runtime
    Tests --> SQLite
```

## Data operation sequence

```mermaid
sequenceDiagram
    participant R as Route
    participant S as Service
    participant Repo as Repository
    participant DB as Database
    R->>S: Request a business operation
    S->>Repo: Read or stage changes
    Repo->>DB: Execute through async session
    DB-->>Repo: Rows or result
    Repo-->>S: Domain objects
    alt operation succeeds
        S->>DB: Commit transaction
        S-->>R: Result
    else operation fails
        S->>DB: Roll back transaction
        S-->>R: Controlled error
    end
```

## Key architecture decisions and trade-offs

| Decision | Benefit | Trade-off at this phase |
|---|---|---|
| One ORM model for SQLite and PostgreSQL | Fast offline tests with a realistic production path | SQLite cannot reproduce every PostgreSQL behavior |
| Sixteen normalized entities | Clear ownership and traceable workflow history | More relationships and migrations to maintain |
| Database row-level security | Defense in depth for stored data | Policies still need live PostgreSQL integration testing |
| Repositories grouped by domain | Keeps SQL away from routes and services | Adds an abstraction layer to simple queries |
| Services own transactions | Multi-repository work can be atomic | Service authors must handle commit and rollback correctly |
| Idempotent demo bootstrap | Reliable, useful local startup | Demo data is not a production provisioning strategy |

## Phase 2 exit and handoff

At the end of Phase 2, CloudDesk has a coherent persistence layer and a repeatable demonstration dataset. Phase 3 can authenticate a user against these profiles, limit requests, and record mutations in the audit table.

The entity and repository behavior is verified locally with SQLite, and the PostgreSQL SQL assets are structurally tested. This phase does **not** claim that a live PostgreSQL or Supabase environment has been exercised.

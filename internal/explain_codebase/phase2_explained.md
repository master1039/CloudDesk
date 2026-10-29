# Phase 2 Explained: Creating the Data Foundation and Demo World

## The simple summary

In Phase 2, I designed how CloudDesk stores information, separated database access from business logic, created protections for the future cloud database, and built a complete demo dataset that loads automatically without creating duplicates.

If Phase 1 built the office, Phase 2 built the filing system. It defines what records exist, how they relate to each other, who may access them, and how the application retrieves them safely.

## Why the data model matters

CloudDesk must eventually answer questions such as:

- Who is the customer?
- Which subscription and workspace do they have?
- What ticket did they open?
- Were there earlier related issues?
- Is there an active service incident?
- What did an automated workflow decide?
- Is a human approval required?
- What actions and audit events occurred?

If these concepts are stored inconsistently, later agents and APIs will disagree. Phase 2 creates one shared definition of the business data before those features are built.

## The sixteen data tables in plain language

The data model contains sixteen related tables. They can be understood in four groups.

### People and accounts

- `profiles` stores support employees and their roles.
- `customers` stores the organizations and people receiving support.
- `subscriptions` stores plan, billing, and seat information.
- `workspaces` stores the customer’s CloudDesk work areas and storage usage.
- `products` identifies the CloudDesk product involved in an issue.

### Support information

- `tickets` stores the main customer issue.
- `ticket_messages` stores the conversation around that issue.
- `support_articles` stores approved help content.
- `incidents` stores known service problems.

### Automated workflow records

- `workflow_runs` stores each attempt to resolve a ticket.
- `workflow_events` stores the step-by-step trace.
- `resolution_actions` stores proposed or executed actions.
- `approval_requests` stores actions waiting for a human decision.
- `escalations` stores cases sent to a named specialist team.

### Memory and accountability

- `customer_memory` stores carefully selected, reusable customer notes.
- `audit_logs` stores a history of state-changing web requests.

Every record has a stable ID plus creation and update times. Relationships prevent records from becoming disconnected. For example, a ticket must belong to a customer, and a workflow event must belong to a workflow run.

## One model for local and cloud environments

I deliberately designed the application model to work with both SQLite and PostgreSQL.

SQLite is a small database that runs locally with no separate server. It makes the offline demo and tests easy to run. PostgreSQL is the intended cloud-grade database.

The SQLAlchemy models act like a translator between Python and either database. I used portable data types, such as text-based UUIDs and standard JSON, so the business code does not need separate local and cloud versions.

This is an important engineering trade-off: I chose portability and a reliable offline demonstration while still providing a dedicated PostgreSQL schema for cloud use.

## PostgreSQL schema, migrations, and access protection

The `database/schema.sql` file is the authoritative PostgreSQL definition of all sixteen tables, indexes, checks, relationships, and automatic update-time triggers.

The first migration is a self-contained baseline. A migration is a recorded database change that can be applied in order. Future changes must add a new migration rather than rewriting history. This makes database evolution reviewable and repeatable.

Row-Level Security, or RLS, adds database-side protection. The current rules follow this principle:

- authenticated browser users may receive approved read access;
- browser users do not receive direct write policies;
- the backend service role performs controlled mutations on the server;
- and the service-role secret is never sent to the browser.

This is defense in depth. Even if a frontend mistake occurs, the database still has its own access rules.

## The repository layer

Business code does not write database queries directly. It uses repositories.

A repository is like a trained librarian. A service asks for “this ticket with its customer context” instead of knowing which shelves and indexes must be searched.

CloudDesk has repository coverage for all sixteen entities, with focused operations such as:

- finding customers by email or external reference;
- loading a customer with subscription, workspaces, previous tickets, and memory;
- filtering tickets by status, category, severity, or customer;
- loading previous resolved tickets;
- retrieving support articles and active incidents;
- and reading workflow events, actions, approvals, escalations, and audit entries.

Repositories prepare changes but do not decide when to permanently commit them. The service layer owns that transaction decision. This makes multi-step business operations safer because the complete operation can succeed or roll back as one unit.

## The demo dataset

Phase 2 creates a realistic but fictional support environment containing:

- 3 support profiles;
- 8 customers across free, pro, business, and enterprise plans;
- 8 workspaces;
- 3 CloudDesk products;
- active service incidents;
- 13 support tickets;
- one initial message for every ticket;
- 4 previous-resolution memory records;
- and 15 knowledge-base articles.

The tickets were chosen to exercise future behavior, not merely fill a table. Examples include:

- `CD-1002`, a refund request that must eventually pause for human approval;
- `CD-1005`, a possible security breach that must be escalated;
- `CD-1009`, a deletion and privacy request;
- `CD-1011`, a disputed payment;
- and `CD-1013`, a prompt-injection attempt that must remain untrusted data.

This gives later phases stable, named scenarios for security, workflow, retrieval, and evaluation tests.

## Automatic and idempotent startup

When CloudDesk starts in demo mode, it follows this flow:

`Start application → create missing tables → check whether demo tables are empty → load sample data once → accept requests`

The bootstrap is idempotent. Idempotent means running it again produces the same final result rather than creating duplicates.

The first seed run reports that data was added. The second reports that seeding was skipped, while the counts remain 8 customers, 13 tickets, and 15 articles.

The same bootstrap service is used by application startup and by `make seed`. This avoids two separate implementations drifting apart.

There is also an idempotent PostgreSQL `seed.sql` for the Supabase SQL editor. The Python bootstrap is used for the SQLite demo, while the SQL seed represents the same core scenario for PostgreSQL.

## A ticket lookup moving through Phase 2

A future service can request a ticket context like this:

`Service → Ticket Repository → database query → ticket + customer + subscription + workspace + messages + memory`

The service receives a complete business object without placing SQL inside an API route or an AI agent. This separation keeps the architecture understandable and testable.

## How I proved it works

The tests verify that:

- the Python models contain exactly the sixteen expected tables;
- SQLite can create the model and save related customer and ticket records;
- PostgreSQL table names, columns, types, and indexes match the Python model;
- all PostgreSQL tables have update triggers and RLS coverage;
- repositories cover all sixteen entities;
- services retain commit and rollback ownership;
- customer and ticket context can be loaded correctly;
- an empty demo database loads the locked sample counts;
- and running the bootstrap twice does not duplicate data.

The exact command behind `make seed` was also run twice locally and showed the expected first-run and second-run behavior.

## What Phase 2 does not claim

The PostgreSQL files were structurally validated, but they were not applied to a live Supabase or PostgreSQL account. No cloud credentials were used.

Phase 2 provides data and access foundations. It does not yet provide the public ticket API, AI agents, frontend, or real customer integrations.

## Closing explanation

The result of Phase 2 is one consistent business data model, usable locally and designed for PostgreSQL, protected by database policies, accessed through clean repositories, and demonstrated with realistic repeatable data. Later phases can now build APIs and intelligent workflows without inventing their own storage rules.

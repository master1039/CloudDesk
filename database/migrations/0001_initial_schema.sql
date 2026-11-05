-- Migration 0001: initial CloudDesk schema and Supabase RLS policies.
-- Generated from database/schema.sql and database/rls_policies.sql at creation time.
-- Never edit this file after it has been applied; add a new numbered migration.

-- CloudDesk PostgreSQL schema. Keep aligned with backend/app/models/entities.py.
-- IDs remain VARCHAR(36) and structured values use JSON (not JSONB) for SQLite parity.

BEGIN;

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS public.customers (
    external_ref VARCHAR(100),
    name VARCHAR(200) NOT NULL,
    email VARCHAR(320) NOT NULL,
    company VARCHAR(200),
    phone VARCHAR(50),
    attributes JSON NOT NULL DEFAULT '{}'::json,
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_customers_external_ref UNIQUE (external_ref)
);

CREATE TABLE IF NOT EXISTS public.products (
    name VARCHAR(160) NOT NULL,
    slug VARCHAR(120) NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    attributes JSON NOT NULL DEFAULT '{}'::json,
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.profiles (
    email VARCHAR(320) NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    role VARCHAR(6) NOT NULL DEFAULT 'viewer',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_profiles_role CHECK (role IN ('viewer', 'agent', 'admin'))
);

CREATE TABLE IF NOT EXISTS public.support_articles (
    slug VARCHAR(200) NOT NULL,
    title VARCHAR(300) NOT NULL,
    category VARCHAR(21) NOT NULL,
    tags JSON NOT NULL DEFAULT '[]'::json,
    summary TEXT NOT NULL,
    body TEXT NOT NULL,
    source_path VARCHAR(500) NOT NULL,
    is_published BOOLEAN NOT NULL DEFAULT TRUE,
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_support_articles_category CHECK (
        category IN ('login_issue', 'billing', 'api_failure', 'workspace_permissions',
                     'storage_quota', 'integration', 'feature_request', 'account', 'security', 'other')
    )
);

CREATE TABLE IF NOT EXISTS public.audit_logs (
    actor_id VARCHAR(36),
    actor_role VARCHAR(6),
    method VARCHAR(10) NOT NULL,
    path VARCHAR(500) NOT NULL,
    status_code INTEGER NOT NULL,
    request_id VARCHAR(128) NOT NULL,
    change_summary JSON NOT NULL DEFAULT '{}'::json,
    ip_address VARCHAR(64),
    user_agent VARCHAR(500),
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_audit_logs_actor FOREIGN KEY (actor_id) REFERENCES public.profiles(id) ON DELETE SET NULL,
    CONSTRAINT ck_audit_logs_role CHECK (actor_role IS NULL OR actor_role IN ('viewer', 'agent', 'admin'))
);

CREATE TABLE IF NOT EXISTS public.incidents (
    product_id VARCHAR(36),
    title VARCHAR(300) NOT NULL,
    description TEXT NOT NULL,
    status VARCHAR(13) NOT NULL DEFAULT 'investigating',
    severity VARCHAR(8) NOT NULL,
    affected_services JSON NOT NULL DEFAULT '[]'::json,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ,
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_incidents_product FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE SET NULL,
    CONSTRAINT ck_incidents_status CHECK (status IN ('investigating', 'identified', 'monitoring', 'resolved')),
    CONSTRAINT ck_incidents_severity CHECK (severity IN ('low', 'medium', 'high', 'critical'))
);

CREATE TABLE IF NOT EXISTS public.subscriptions (
    customer_id VARCHAR(36) NOT NULL,
    plan VARCHAR(10) NOT NULL DEFAULT 'free',
    status VARCHAR(8) NOT NULL DEFAULT 'active',
    seats INTEGER NOT NULL DEFAULT 1 CHECK (seats > 0),
    amount NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (amount >= 0),
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    billing_interval VARCHAR(20) NOT NULL DEFAULT 'monthly',
    current_period_end TIMESTAMPTZ,
    attributes JSON NOT NULL DEFAULT '{}'::json,
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_subscriptions_customer UNIQUE (customer_id),
    CONSTRAINT fk_subscriptions_customer FOREIGN KEY (customer_id) REFERENCES public.customers(id) ON DELETE CASCADE,
    CONSTRAINT ck_subscriptions_plan CHECK (plan IN ('free', 'pro', 'business', 'enterprise')),
    CONSTRAINT ck_subscriptions_status CHECK (status IN ('active', 'past_due', 'canceled', 'trialing'))
);

CREATE TABLE IF NOT EXISTS public.workspaces (
    customer_id VARCHAR(36) NOT NULL,
    name VARCHAR(200) NOT NULL,
    slug VARCHAR(120) NOT NULL,
    storage_used_bytes BIGINT NOT NULL DEFAULT 0 CHECK (storage_used_bytes >= 0),
    storage_limit_bytes BIGINT NOT NULL DEFAULT 0 CHECK (storage_limit_bytes >= 0),
    settings JSON NOT NULL DEFAULT '{}'::json,
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_workspaces_customer FOREIGN KEY (customer_id) REFERENCES public.customers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.tickets (
    display_id VARCHAR(20) NOT NULL,
    customer_id VARCHAR(36) NOT NULL,
    workspace_id VARCHAR(36),
    product_id VARCHAR(36),
    assigned_to_id VARCHAR(36),
    subject VARCHAR(500) NOT NULL,
    body TEXT NOT NULL,
    channel VARCHAR(5) NOT NULL,
    status VARCHAR(19) NOT NULL DEFAULT 'new',
    category VARCHAR(21),
    severity VARCHAR(8),
    summary VARCHAR(500),
    injection_detected BOOLEAN NOT NULL DEFAULT FALSE,
    attributes JSON NOT NULL DEFAULT '{}'::json,
    resolved_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_tickets_customer FOREIGN KEY (customer_id) REFERENCES public.customers(id) ON DELETE RESTRICT,
    CONSTRAINT fk_tickets_workspace FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id) ON DELETE SET NULL,
    CONSTRAINT fk_tickets_product FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE SET NULL,
    CONSTRAINT fk_tickets_assignee FOREIGN KEY (assigned_to_id) REFERENCES public.profiles(id) ON DELETE SET NULL,
    CONSTRAINT ck_tickets_channel CHECK (channel IN ('email', 'chat', 'web', 'api')),
    CONSTRAINT ck_tickets_status CHECK (
        status IN ('new', 'in_progress', 'waiting_on_customer', 'waiting_on_approval',
                   'escalated', 'resolved', 'closed')
    ),
    CONSTRAINT ck_tickets_category CHECK (
        category IS NULL OR category IN ('login_issue', 'billing', 'api_failure', 'workspace_permissions',
                                         'storage_quota', 'integration', 'feature_request', 'account',
                                         'security', 'other')
    ),
    CONSTRAINT ck_tickets_severity CHECK (severity IS NULL OR severity IN ('low', 'medium', 'high', 'critical'))
);

CREATE TABLE IF NOT EXISTS public.ticket_messages (
    ticket_id VARCHAR(36) NOT NULL,
    direction VARCHAR(8) NOT NULL,
    author_id VARCHAR(36),
    author_name VARCHAR(200),
    body TEXT NOT NULL,
    channel VARCHAR(5),
    attributes JSON NOT NULL DEFAULT '{}'::json,
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ticket_messages_ticket FOREIGN KEY (ticket_id) REFERENCES public.tickets(id) ON DELETE CASCADE,
    CONSTRAINT fk_ticket_messages_author FOREIGN KEY (author_id) REFERENCES public.profiles(id) ON DELETE SET NULL,
    CONSTRAINT ck_ticket_messages_direction CHECK (direction IN ('inbound', 'outbound', 'internal')),
    CONSTRAINT ck_ticket_messages_channel CHECK (channel IS NULL OR channel IN ('email', 'chat', 'web', 'api'))
);

CREATE TABLE IF NOT EXISTS public.workflow_runs (
    ticket_id VARCHAR(36) NOT NULL,
    thread_id VARCHAR(100) NOT NULL,
    status VARCHAR(19) NOT NULL DEFAULT 'queued',
    current_node VARCHAR(100),
    state JSON NOT NULL DEFAULT '{}'::json,
    completed_nodes JSON NOT NULL DEFAULT '[]'::json,
    errors JSON NOT NULL DEFAULT '[]'::json,
    token_usage JSON NOT NULL DEFAULT '{}'::json,
    estimated_cost NUMERIC(12, 6) NOT NULL DEFAULT 0 CHECK (estimated_cost >= 0),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_workflow_runs_ticket FOREIGN KEY (ticket_id) REFERENCES public.tickets(id) ON DELETE CASCADE,
    CONSTRAINT ck_workflow_runs_status CHECK (
        status IN ('queued', 'running', 'waiting_on_approval', 'completed', 'failed')
    )
);

CREATE TABLE IF NOT EXISTS public.customer_memory (
    customer_id VARCHAR(36) NOT NULL,
    memory_type VARCHAR(15) NOT NULL,
    content TEXT NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    source_ticket_id VARCHAR(36),
    source_workflow_id VARCHAR(36),
    attributes JSON NOT NULL DEFAULT '{}'::json,
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_customer_memory_dedup UNIQUE (customer_id, memory_type, fingerprint),
    CONSTRAINT fk_customer_memory_customer FOREIGN KEY (customer_id) REFERENCES public.customers(id) ON DELETE CASCADE,
    CONSTRAINT fk_customer_memory_ticket FOREIGN KEY (source_ticket_id) REFERENCES public.tickets(id) ON DELETE SET NULL,
    CONSTRAINT fk_customer_memory_workflow FOREIGN KEY (source_workflow_id) REFERENCES public.workflow_runs(id) ON DELETE SET NULL,
    CONSTRAINT ck_customer_memory_type CHECK (memory_type IN ('preference', 'past_issue', 'troubleshooting', 'note'))
);

CREATE TABLE IF NOT EXISTS public.escalations (
    ticket_id VARCHAR(36) NOT NULL,
    workflow_id VARCHAR(36),
    team VARCHAR(120) NOT NULL,
    reason TEXT NOT NULL,
    policy_rules JSON NOT NULL DEFAULT '[]'::json,
    priority VARCHAR(8) NOT NULL DEFAULT 'medium',
    status VARCHAR(11) NOT NULL DEFAULT 'open',
    resolved_at TIMESTAMPTZ,
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_escalations_ticket FOREIGN KEY (ticket_id) REFERENCES public.tickets(id) ON DELETE CASCADE,
    CONSTRAINT fk_escalations_workflow FOREIGN KEY (workflow_id) REFERENCES public.workflow_runs(id) ON DELETE SET NULL,
    CONSTRAINT ck_escalations_priority CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT ck_escalations_status CHECK (status IN ('open', 'in_progress', 'resolved', 'closed'))
);

CREATE TABLE IF NOT EXISTS public.resolution_actions (
    ticket_id VARCHAR(36) NOT NULL,
    workflow_id VARCHAR(36) NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    arguments JSON NOT NULL DEFAULT '{}'::json,
    requires_approval BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(19) NOT NULL DEFAULT 'planned',
    result JSON,
    error TEXT,
    executed_at TIMESTAMPTZ,
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_resolution_actions_ticket FOREIGN KEY (ticket_id) REFERENCES public.tickets(id) ON DELETE CASCADE,
    CONSTRAINT fk_resolution_actions_workflow FOREIGN KEY (workflow_id) REFERENCES public.workflow_runs(id) ON DELETE CASCADE,
    CONSTRAINT ck_resolution_actions_status CHECK (
        status IN ('planned', 'waiting_on_approval', 'approved', 'rejected',
                   'executing', 'completed', 'failed')
    )
);

CREATE TABLE IF NOT EXISTS public.workflow_events (
    workflow_id VARCHAR(36) NOT NULL,
    ticket_id VARCHAR(36) NOT NULL,
    event_type VARCHAR(80) NOT NULL,
    node VARCHAR(100),
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    token_usage JSON NOT NULL DEFAULT '{}'::json,
    estimated_cost NUMERIC(12, 6) NOT NULL DEFAULT 0 CHECK (estimated_cost >= 0),
    input_summary JSON NOT NULL DEFAULT '{}'::json,
    output_summary JSON NOT NULL DEFAULT '{}'::json,
    details JSON NOT NULL DEFAULT '{}'::json,
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_workflow_events_workflow FOREIGN KEY (workflow_id) REFERENCES public.workflow_runs(id) ON DELETE CASCADE,
    CONSTRAINT fk_workflow_events_ticket FOREIGN KEY (ticket_id) REFERENCES public.tickets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.approval_requests (
    ticket_id VARCHAR(36) NOT NULL,
    workflow_id VARCHAR(36) NOT NULL,
    resolution_action_id VARCHAR(36),
    action VARCHAR(100) NOT NULL,
    arguments JSON NOT NULL DEFAULT '{}'::json,
    reason TEXT NOT NULL,
    status VARCHAR(8) NOT NULL DEFAULT 'pending',
    requested_by_id VARCHAR(36),
    decided_by_id VARCHAR(36),
    decision_note TEXT,
    decided_at TIMESTAMPTZ,
    id VARCHAR(36) PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_approval_requests_action UNIQUE (resolution_action_id),
    CONSTRAINT fk_approval_requests_ticket FOREIGN KEY (ticket_id) REFERENCES public.tickets(id) ON DELETE CASCADE,
    CONSTRAINT fk_approval_requests_workflow FOREIGN KEY (workflow_id) REFERENCES public.workflow_runs(id) ON DELETE CASCADE,
    CONSTRAINT fk_approval_requests_action FOREIGN KEY (resolution_action_id) REFERENCES public.resolution_actions(id) ON DELETE SET NULL,
    CONSTRAINT fk_approval_requests_requested_by FOREIGN KEY (requested_by_id) REFERENCES public.profiles(id) ON DELETE SET NULL,
    CONSTRAINT fk_approval_requests_decided_by FOREIGN KEY (decided_by_id) REFERENCES public.profiles(id) ON DELETE SET NULL,
    CONSTRAINT ck_approval_requests_status CHECK (status IN ('pending', 'approved', 'rejected'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_products_slug ON public.products(slug);
CREATE UNIQUE INDEX IF NOT EXISTS ix_profiles_email ON public.profiles(email);
CREATE UNIQUE INDEX IF NOT EXISTS ix_support_articles_slug ON public.support_articles(slug);
CREATE INDEX IF NOT EXISTS ix_support_articles_category ON public.support_articles(category);
CREATE INDEX IF NOT EXISTS ix_customers_email ON public.customers(email);
CREATE INDEX IF NOT EXISTS ix_customers_name ON public.customers(name);
CREATE INDEX IF NOT EXISTS ix_audit_logs_actor_created ON public.audit_logs(actor_id, created_at);
CREATE INDEX IF NOT EXISTS ix_audit_logs_actor_id ON public.audit_logs(actor_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_path ON public.audit_logs(path);
CREATE INDEX IF NOT EXISTS ix_audit_logs_request_id ON public.audit_logs(request_id);
CREATE INDEX IF NOT EXISTS ix_incidents_product_id ON public.incidents(product_id);
CREATE INDEX IF NOT EXISTS ix_incidents_status ON public.incidents(status);
CREATE INDEX IF NOT EXISTS ix_incidents_severity ON public.incidents(severity);
CREATE UNIQUE INDEX IF NOT EXISTS ix_workspaces_slug ON public.workspaces(slug);
CREATE INDEX IF NOT EXISTS ix_workspaces_customer_id ON public.workspaces(customer_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_tickets_display_id ON public.tickets(display_id);
CREATE INDEX IF NOT EXISTS ix_tickets_customer_created_at ON public.tickets(customer_id, created_at);
CREATE INDEX IF NOT EXISTS ix_tickets_status_severity ON public.tickets(status, severity);
CREATE INDEX IF NOT EXISTS ix_tickets_assigned_to_id ON public.tickets(assigned_to_id);
CREATE INDEX IF NOT EXISTS ix_tickets_category ON public.tickets(category);
CREATE INDEX IF NOT EXISTS ix_tickets_customer_id ON public.tickets(customer_id);
CREATE INDEX IF NOT EXISTS ix_tickets_product_id ON public.tickets(product_id);
CREATE INDEX IF NOT EXISTS ix_tickets_severity ON public.tickets(severity);
CREATE INDEX IF NOT EXISTS ix_tickets_status ON public.tickets(status);
CREATE INDEX IF NOT EXISTS ix_tickets_workspace_id ON public.tickets(workspace_id);
CREATE INDEX IF NOT EXISTS ix_ticket_messages_ticket_id ON public.ticket_messages(ticket_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_workflow_runs_thread_id ON public.workflow_runs(thread_id);
CREATE INDEX IF NOT EXISTS ix_workflow_runs_ticket_id ON public.workflow_runs(ticket_id);
CREATE INDEX IF NOT EXISTS ix_workflow_runs_status ON public.workflow_runs(status);
CREATE INDEX IF NOT EXISTS ix_customer_memory_customer_id ON public.customer_memory(customer_id);
CREATE INDEX IF NOT EXISTS ix_customer_memory_memory_type ON public.customer_memory(memory_type);
CREATE INDEX IF NOT EXISTS ix_escalations_ticket_id ON public.escalations(ticket_id);
CREATE INDEX IF NOT EXISTS ix_escalations_status ON public.escalations(status);
CREATE INDEX IF NOT EXISTS ix_escalations_team ON public.escalations(team);
CREATE INDEX IF NOT EXISTS ix_escalations_workflow_id ON public.escalations(workflow_id);
CREATE INDEX IF NOT EXISTS ix_resolution_actions_ticket_id ON public.resolution_actions(ticket_id);
CREATE INDEX IF NOT EXISTS ix_resolution_actions_workflow_id ON public.resolution_actions(workflow_id);
CREATE INDEX IF NOT EXISTS ix_resolution_actions_status ON public.resolution_actions(status);
CREATE INDEX IF NOT EXISTS ix_workflow_events_workflow_created ON public.workflow_events(workflow_id, created_at);
CREATE INDEX IF NOT EXISTS ix_workflow_events_event_type ON public.workflow_events(event_type);
CREATE INDEX IF NOT EXISTS ix_workflow_events_node ON public.workflow_events(node);
CREATE INDEX IF NOT EXISTS ix_workflow_events_ticket_id ON public.workflow_events(ticket_id);
CREATE INDEX IF NOT EXISTS ix_workflow_events_workflow_id ON public.workflow_events(workflow_id);
CREATE INDEX IF NOT EXISTS ix_approval_requests_ticket_id ON public.approval_requests(ticket_id);
CREATE INDEX IF NOT EXISTS ix_approval_requests_workflow_id ON public.approval_requests(workflow_id);
CREATE INDEX IF NOT EXISTS ix_approval_requests_status ON public.approval_requests(status);

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'profiles', 'customers', 'subscriptions', 'workspaces', 'products', 'tickets',
        'ticket_messages', 'support_articles', 'incidents', 'workflow_runs', 'workflow_events',
        'resolution_actions', 'approval_requests', 'escalations', 'customer_memory', 'audit_logs'
    ]
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%I_updated_at ON public.%I', table_name, table_name);
        EXECUTE format(
            'CREATE TRIGGER trg_%I_updated_at BEFORE UPDATE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()',
            table_name,
            table_name
        );
    END LOOP;
END;
$$;

COMMIT;

-- CloudDesk Supabase row-level security.
-- Browser sessions are read-only; backend mutations use the server-side service role.

BEGIN;

CREATE OR REPLACE FUNCTION public.current_app_role()
RETURNS TEXT
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT role
    FROM public.profiles
    WHERE id = auth.uid()::text
      AND is_active = TRUE
    LIMIT 1
$$;

REVOKE ALL ON FUNCTION public.current_app_role() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.current_app_role() TO authenticated, service_role;
GRANT USAGE ON SCHEMA public TO authenticated, service_role;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'profiles', 'customers', 'subscriptions', 'workspaces', 'products', 'tickets',
        'ticket_messages', 'support_articles', 'incidents', 'workflow_runs', 'workflow_events',
        'resolution_actions', 'approval_requests', 'escalations', 'customer_memory', 'audit_logs'
    ]
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);

        EXECUTE format('DROP POLICY IF EXISTS service_role_all ON public.%I', table_name);
        EXECUTE format(
            'CREATE POLICY service_role_all ON public.%I FOR ALL TO service_role '
            'USING (TRUE) WITH CHECK (TRUE)',
            table_name
        );

        EXECUTE format('GRANT ALL ON TABLE public.%I TO service_role', table_name);
    END LOOP;
END;
$$;

DROP POLICY IF EXISTS profile_self_read ON public.profiles;
CREATE POLICY profile_self_read
ON public.profiles
FOR SELECT
TO authenticated
USING (id = auth.uid()::text OR public.current_app_role() = 'admin');
GRANT SELECT ON public.profiles TO authenticated;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'customers', 'subscriptions', 'workspaces', 'products', 'tickets', 'ticket_messages',
        'support_articles', 'incidents', 'workflow_runs', 'workflow_events', 'resolution_actions',
        'approval_requests', 'escalations', 'customer_memory', 'audit_logs'
    ]
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS support_read ON public.%I', table_name);
        EXECUTE format(
            'CREATE POLICY support_read ON public.%I FOR SELECT TO authenticated '
            'USING (public.current_app_role() IN (''viewer'', ''agent'', ''admin''))',
            table_name
        );
        EXECUTE format('GRANT SELECT ON TABLE public.%I TO authenticated', table_name);
    END LOOP;
END;
$$;

-- No INSERT, UPDATE, or DELETE policy is granted to authenticated browser users.
-- The FastAPI backend uses service_role and still enforces JWT/RBAC/tool policy in application code.

COMMIT;


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

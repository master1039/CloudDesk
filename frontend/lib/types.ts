/** Shared transport types for the CloudDesk v1 API contract. */

export type Role = "viewer" | "agent" | "admin";
export type TicketCategory =
  | "login_issue"
  | "billing"
  | "api_failure"
  | "workspace_permissions"
  | "storage_quota"
  | "integration"
  | "feature_request"
  | "account"
  | "security"
  | "other";
export type TicketStatus =
  | "new"
  | "in_progress"
  | "waiting_on_customer"
  | "waiting_on_approval"
  | "escalated"
  | "resolved"
  | "closed";
export type Severity = "low" | "medium" | "high" | "critical";
export type Channel = "email" | "chat" | "web" | "api";
export type MessageDirection = "inbound" | "outbound" | "internal";
export type SubscriptionPlan = "free" | "pro" | "business" | "enterprise";
export type SubscriptionStatus = "active" | "past_due" | "canceled" | "trialing";
export type MemoryType = "preference" | "past_issue" | "troubleshooting" | "note";
export type WorkflowStatus =
  | "queued"
  | "running"
  | "waiting_on_approval"
  | "completed"
  | "failed";
export type ApprovalStatus = "pending" | "approved" | "rejected";
export type EscalationStatus = "open" | "in_progress" | "resolved" | "closed";
export type RetrievalMode = "hybrid" | "semantic" | "keyword";

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface CreateTicketRequest {
  customer_id: string;
  subject: string;
  body: string;
  channel: Channel;
}

export interface TicketListParams {
  status?: TicketStatus;
  severity?: Severity;
  category?: TicketCategory;
  channel?: Channel;
  customer_id?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

export interface TicketMessage {
  id: string;
  ticket_id: string;
  direction: MessageDirection;
  author: string | null;
  body: string;
  created_at: string;
}

export interface TicketSummary {
  id: string;
  display_id: string;
  subject: string;
  customer_id: string;
  customer_name: string;
  channel: Channel;
  status: TicketStatus;
  category: TicketCategory | null;
  severity: Severity | null;
  summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowReference {
  id: string;
  status: WorkflowStatus;
  url: string;
}

export interface ApprovalReference {
  id: string;
  status: ApprovalStatus;
  url: string;
}

export interface EscalationReference {
  id: string;
  status: EscalationStatus;
  team: string;
  url: string;
}

export interface CustomerContextLinks {
  customer: string;
  subscription: string | null;
  workspace: string | null;
  previous_tickets: string;
}

export interface TicketDetail extends TicketSummary {
  body: string;
  messages: TicketMessage[];
  workflow: WorkflowReference | null;
  approval: ApprovalReference | null;
  escalation: EscalationReference | null;
  customer_context_links: CustomerContextLinks;
}

export type TicketListResponse = PaginatedResponse<TicketSummary>;

export interface CustomerListParams {
  search?: string;
  plan?: SubscriptionPlan;
  limit?: number;
  offset?: number;
}

export interface CustomerSummary {
  id: string;
  name: string;
  email: string;
  company: string | null;
  plan: SubscriptionPlan | null;
  workspace_id: string | null;
  created_at: string;
}

export interface Subscription {
  id: string;
  plan: SubscriptionPlan;
  status: SubscriptionStatus;
  seats: number;
  amount: string;
  currency: string;
  billing_interval: string;
  current_period_end: string | null;
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  storage_used_bytes: number;
  storage_limit_bytes: number;
}

export interface CustomerMemoryNote {
  id: string;
  memory_type: MemoryType;
  content: string;
  source_ticket_id: string | null;
  created_at: string;
}

export interface CustomerDetail extends CustomerSummary {
  subscription: Subscription | null;
  workspace: Workspace | null;
  previous_tickets: TicketSummary[];
  memory_notes: CustomerMemoryNote[];
}

export type CustomerListResponse = PaginatedResponse<CustomerSummary>;

export interface KnowledgeListParams {
  category?: TicketCategory;
  search?: string;
  limit?: number;
  offset?: number;
}

export interface KnowledgeArticleSummary {
  id: string;
  slug: string;
  title: string;
  category: TicketCategory;
  tags: string[];
  summary: string;
  updated_at: string;
}

export interface KnowledgeArticle extends KnowledgeArticleSummary {
  body: string;
}

export type KnowledgeListResponse = PaginatedResponse<KnowledgeArticleSummary>;

export interface KnowledgeSearchRequest {
  query: string;
  category?: TicketCategory;
  mode?: RetrievalMode;
  top_k?: number;
}

export interface Evidence {
  id: string;
  title: string;
  source: string;
  snippet: string;
  score: number;
  url: string;
  article_id: string;
}

export interface KnowledgeSearchResponse {
  items: Evidence[];
}

export interface ReindexRequest {
  embedding_provider?: string;
  embedding_model?: string;
}

export interface ReindexJob {
  id: string;
  status: "completed";
  collection: string;
  article_count: number;
  chunk_count: number;
  indexed_count: number;
  created_at: string;
}


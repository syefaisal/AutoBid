export interface Campaign {
  id: string;
  name: string;
  advertiser: string;
  status: "active" | "paused" | "ended" | "pending";
  optimization_goal: "cpa" | "roas" | "ctr" | "reach" | "viewability";
  daily_budget_usd: number;
  spend_today_usd: number;
  pacing_rate: number;
  bid_modifier: number;
  base_bid_cpm: number;
  impressions: number;
  clicks: number;
  conversions: number;
  ctr_pct: number;
  cpa_usd: number | null;
  roas: number | null;
}

export interface CampaignMetrics extends Campaign {
  spend_total_usd: number;
  budget_utilization_pct: number;
  effective_bid_cpm: number;
  cvr_pct: number;
  target_cpa: number | null;
  target_roas: number | null;
  targeting: Record<string, unknown>;
  supply_sources: string[];
  pacing_type: string;
}

export interface HistoryPoint {
  hour_ts: string;
  impressions: number;
  clicks: number;
  conversions: number;
  spend_usd: number;
  revenue_usd: number;
  avg_bid_cpm: number;
  win_rate: number;
  fill_rate: number;
}

export interface AuditLog {
  id: string;
  trace_id: string;
  action_type: string;
  campaign_id: string;
  status: string;
  is_dry_run: boolean;
  requires_approval: boolean;
  approved_by: string | null;
  params_before: Record<string, unknown>;
  params_requested: Record<string, unknown>;
  params_after: Record<string, unknown> | null;
  agent_rationale: string | null;
  rag_sources: string[];
  latency_ms: number | null;
  error_message: string | null;
  created_at: string | null;
  executed_at: string | null;
}

export interface AgentSession {
  id: string;
  trace_id: string;
  query: string;
  status: string;
  is_dry_run: boolean;
  tool_calls: number;
  rag_retrievals: number;
  actions_taken: number;
  total_latency_ms: number | null;
  tokens_in: number;
  tokens_out: number;
  created_at: string | null;
  final_answer?: string;
}

export interface Experiment {
  id: string;
  name: string;
  description: string;
  hypothesis: string;
  metric: string;
  status: string;
  control_campaign_ids: string[];
  treatment_campaign_ids: string[];
  control_metric_value: number | null;
  treatment_metric_value: number | null;
  lift_pct: number | null;
  p_value: number | null;
  is_significant: boolean | null;
  start_date: string | null;
  end_date: string | null;
}

export interface TraceSpan {
  span_id: string;
  parent_span_id: string | null;
  name: string;
  service: string;
  start_time_ms: number;
  end_time_ms: number | null;
  duration_ms: number | null;
  status: string;
  attributes: Record<string, unknown>;
  events: Array<{ name: string; time_ms: number; attributes: Record<string, unknown> }>;
}

export interface Trace {
  trace_id: string;
  spans: TraceSpan[];
}

export interface TraceSummary {
  trace_id: string;
  root_span: string;
  service: string;
  start_time_ms: number;
  duration_ms: number | null;
  span_count: number;
  status: string;
}

// Agent streaming event types
export type AgentEvent =
  | { type: "text_delta"; text: string; session_id: string }
  | { type: "tool_call"; tool_name: string; tool_input: Record<string, unknown>; tool_use_id: string; session_id: string }
  | { type: "tool_result"; tool_name: string; tool_use_id: string; result: Record<string, unknown>; session_id: string }
  | { type: "done"; session_id: string; trace_id: string; total_latency_ms: number; tool_calls: number; rag_retrievals: number; tokens_in: number; tokens_out: number; dry_run: boolean }
  | { type: "error"; error: string; session_id: string };

// Workflow (LangGraph) types
export type WorkflowNodeName = "planner" | "analyst" | "optimizer" | "auditor" | "executor" | "reviewer";

export interface PlanStep {
  step_id: string;
  title: string;
  description: string;
  step_type: string;
  campaign_ids: string[];
  priority: string;
  status: "pending" | "in_progress" | "completed" | "skipped";
}

export interface ProposedAction {
  action_id: string;
  action_type: string;
  campaign_id: string;
  params: Record<string, unknown>;
  rationale: string;
  confidence: number;
  approval_required?: boolean;
}

export interface AuditFinding {
  finding_id: string;
  action_id: string;
  severity: "pass" | "info" | "warning" | "block";
  finding: string;
  policy_source: string;
  recommendation: string;
  requires_human_approval: boolean;
}

export type WorkflowEvent =
  | { type: "workflow_start"; session_id: string; trace_id: string; goal: string }
  | { type: "node_start"; node: WorkflowNodeName }
  | { type: "node_end"; node: WorkflowNodeName }
  | { type: "plan_created"; title: string; steps: PlanStep[]; step_count: number }
  | { type: "metrics_fetched"; campaign_id: string; campaign_name: string; pacing_rate: number; cpa_usd: number; spend_today_usd: number; budget_utilization_pct: number }
  | { type: "rag_retrieved"; query: string; sources: string[]; result_count: number }
  | { type: "optimizer_skipped"; reason: string }
  | { type: "actions_proposed"; count: number; actions: ProposedAction[] }
  | { type: "audit_skipped"; reason: string }
  | { type: "action_approved"; action_id: string; action_type: string; severity?: string }
  | { type: "action_blocked"; action_id: string; action_type: string; reason: string; policy_source: string }
  | { type: "action_pending_approval"; action_id: string; action_type: string; finding: string }
  | { type: "audit_complete"; approved: number; blocked: number; pending_approval: number; findings: AuditFinding[] }
  | { type: "action_executed"; action_id: string; action_type: string; campaign_id: string; status: string; audit_id: string; dry_run: boolean }
  | { type: "optimizer_fallback"; reason: string; action_count: number }
  | { type: "auditor_fallback"; reason: string }
  | { type: "action_gated"; action_id: string; action_type: string; campaign_id: string; dry_run: boolean; reasons: string[] }
  | { type: "action_passed_gate"; action_id: string; action_type: string; campaign_id: string }
  | { type: "gatekeeper_complete"; forwarded: number; gated: number; dry_run: boolean }
  | { type: "review_complete"; summary: string; optimization_complete: boolean; next_iteration_notes: string; steps_completed: number; steps_total: number }
  | { type: "workflow_interrupted"; session_id: string; pending_actions: ProposedAction[]; resume_url: string }
  | { type: "workflow_complete"; session_id: string; review_summary: string; optimization_complete: boolean; actions_executed: number; actions_blocked: number }
  | { type: "workflow_resumed"; session_id: string; approved: number; rejected: number }
  | { type: "error"; error: string };

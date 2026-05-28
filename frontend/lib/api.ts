import type { Campaign, CampaignMetrics, HistoryPoint, AuditLog, AgentSession, Experiment, TraceSummary, Trace, AgentEvent, WorkflowEvent } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json();
}

export async function* streamWorkflow(
  goal: string,
  dryRun: boolean,
  sessionId?: string,
  requireApproval = true,
): AsyncGenerator<WorkflowEvent> {
  const res = await fetch(`${API_BASE}/agent/workflow/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      goal,
      dry_run: dryRun,
      session_id: sessionId,
      require_approval: requireApproval,
    }),
  });
  if (!res.ok) throw new Error(`Workflow run failed: ${res.status}`);
  yield* _readSSE<WorkflowEvent>(res);
}

export async function* resumeWorkflow(
  sessionId: string,
  approvedIds: string[],
  rejectedIds: string[],
): AsyncGenerator<WorkflowEvent> {
  const res = await fetch(`${API_BASE}/agent/sessions/${sessionId}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved_ids: approvedIds, rejected_ids: rejectedIds }),
  });
  if (!res.ok) throw new Error(`Resume failed: ${res.status}`);
  yield* _readSSE<WorkflowEvent>(res);
}

async function* _readSSE<T>(res: Response): AsyncGenerator<T> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6).trim();
        if (data === "[DONE]") return;
        try { yield JSON.parse(data) as T; } catch {}
      }
    }
  }
}

export const api = {
  campaigns: {
    list: () => get<Campaign[]>("/campaigns/"),
    metrics: (id: string) => get<CampaignMetrics>(`/campaigns/${id}/metrics`),
    history: (id: string, hours = 24) => get<HistoryPoint[]>(`/campaigns/${id}/history?hours=${hours}`),
  },
  agent: {
    sessions: () => get<AgentSession[]>("/agent/sessions"),
    session: (id: string) => get<AgentSession>(`/agent/sessions/${id}`),
  },
  audit: {
    list: (params?: { campaign_id?: string; status?: string }) => {
      const qs = params ? "?" + new URLSearchParams(params as Record<string, string>).toString() : "";
      return get<AuditLog[]>(`/audit/${qs}`);
    },
    approve: (id: string, approvedBy = "campaign_manager") =>
      post<{ status: string }>(`/audit/${id}/approve`, { approved_by: approvedBy }),
    reject: (id: string) => post<{ status: string }>(`/audit/${id}/reject`, {}),
    rollback: (id: string) => post<{ status: string }>(`/audit/${id}/rollback`, {}),
  },
  experiments: {
    list: () => get<Experiment[]>("/experiments/"),
  },
  traces: {
    list: () => get<TraceSummary[]>("/traces/"),
    get: (traceId: string) => get<Trace>(`/traces/${traceId}`),
  },
};

export async function* streamAgentRun(
  query: string,
  dryRun: boolean
): AsyncGenerator<AgentEvent> {
  const res = await fetch(`${API_BASE}/agent/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, dry_run: dryRun }),
  });
  if (!res.ok) throw new Error(`Agent run failed: ${res.status}`);
  yield* _readSSE<AgentEvent>(res);
}

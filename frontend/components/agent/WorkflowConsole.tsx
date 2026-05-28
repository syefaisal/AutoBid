"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { streamWorkflow, resumeWorkflow } from "@/lib/api";
import type {
  WorkflowEvent,
  WorkflowNodeName,
  PlanStep,
  ProposedAction,
  AuditFinding,
} from "@/lib/types";

const STORAGE_KEY = "autobid:workflow";

interface PersistedState {
  goal: string;
  events: WorkflowEvent[];
  nodeStatuses: Record<WorkflowNodeName, NodeStatus>;
  planSteps: PlanStep[];
  findings: AuditFinding[];
  approval: ApprovalGate | null;
  selectedApprovals: string[];
  summary: { text: string; complete: boolean } | null;
  sessionId: string | null;
}

function loadSaved(): PersistedState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PersistedState) : null;
  } catch {
    return null;
  }
}

// ── Constants ─────────────────────────────────────────────────────────────────

const NODE_ORDER: WorkflowNodeName[] = [
  "planner", "analyst", "optimizer", "auditor", "executor", "reviewer",
];

const NODE_LABELS: Record<WorkflowNodeName, string> = {
  planner: "Planner",
  analyst: "Analyst",
  optimizer: "Optimizer",
  auditor: "Auditor",
  executor: "Executor",
  reviewer: "Reviewer",
};

const NODE_COLORS: Record<WorkflowNodeName, string> = {
  planner:   "bg-indigo-500/20 border-indigo-500 text-indigo-300",
  analyst:   "bg-cyan-500/20 border-cyan-500 text-cyan-300",
  optimizer: "bg-violet-500/20 border-violet-500 text-violet-300",
  auditor:   "bg-amber-500/20 border-amber-500 text-amber-300",
  executor:  "bg-emerald-500/20 border-emerald-500 text-emerald-300",
  reviewer:  "bg-rose-500/20 border-rose-500 text-rose-300",
};

const SEVERITY_COLORS: Record<string, string> = {
  pass:    "text-emerald-400",
  info:    "text-cyan-400",
  warning: "text-amber-400",
  block:   "text-red-400",
};

// ── Types ─────────────────────────────────────────────────────────────────────

type NodeStatus = "idle" | "active" | "done";

interface ApprovalGate {
  sessionId: string;
  actions: ProposedAction[];
}

// ── Component ─────────────────────────────────────────────────────────────────

const IDLE_NODES: Record<WorkflowNodeName, NodeStatus> = {
  planner: "idle", analyst: "idle", optimizer: "idle",
  auditor: "idle", executor: "idle", reviewer: "idle",
};

export default function WorkflowConsole() {
  // Seed all state from sessionStorage on first render
  const saved = useRef<PersistedState | null>(null);
  if (saved.current === null) saved.current = loadSaved();
  const s = saved.current;

  const [goal, setGoal] = useState(s?.goal ?? "");
  const [dryRun, setDryRun] = useState(true);
  const [requireApproval, setRequireApproval] = useState(true);
  const [running, setRunning] = useState(false);

  const [nodeStatuses, setNodeStatuses] = useState<Record<WorkflowNodeName, NodeStatus>>(
    s?.nodeStatuses ?? IDLE_NODES
  );
  const [activeNode, setActiveNode] = useState<WorkflowNodeName | null>(null);

  const [planSteps, setPlanSteps] = useState<PlanStep[]>(s?.planSteps ?? []);
  const [findings, setFindings] = useState<AuditFinding[]>(s?.findings ?? []);
  const [events, setEvents] = useState<WorkflowEvent[]>(s?.events ?? []);
  const [approval, setApproval] = useState<ApprovalGate | null>(s?.approval ?? null);
  const [selectedApprovals, setSelectedApprovals] = useState<Set<string>>(
    new Set(s?.selectedApprovals ?? [])
  );
  const [summary, setSummary] = useState<{ text: string; complete: boolean } | null>(
    s?.summary ?? null
  );
  const [sessionId, setSessionId] = useState<string | null>(s?.sessionId ?? null);
  const logRef = useRef<HTMLDivElement>(null);

  const isRestored = !!(s?.events?.length);

  // Persist state to sessionStorage whenever it changes
  useEffect(() => {
    const state: PersistedState = {
      goal, events, nodeStatuses, planSteps, findings,
      approval, selectedApprovals: [...selectedApprovals],
      summary, sessionId,
    };
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {}
  }, [goal, events, nodeStatuses, planSteps, findings, approval, selectedApprovals, summary, sessionId]);

  const handleClear = () => {
    try { sessionStorage.removeItem(STORAGE_KEY); } catch {}
    saved.current = null;
    setGoal("");
    setEvents([]);
    setPlanSteps([]);
    setFindings([]);
    setApproval(null);
    setSelectedApprovals(new Set());
    setSummary(null);
    setSessionId(null);
    setNodeStatuses(IDLE_NODES);
    setActiveNode(null);
  };

  const pushEvent = useCallback((ev: WorkflowEvent) => {
    setEvents(prev => [...prev, ev]);
    setTimeout(() => logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" }), 50);
  }, []);

  const processEvents = useCallback(async (gen: AsyncGenerator<WorkflowEvent>) => {
    for await (const ev of gen) {
      pushEvent(ev);
      switch (ev.type) {
        case "workflow_start":
          setSessionId(ev.session_id);
          break;
        case "node_start":
          setActiveNode(ev.node);
          setNodeStatuses(s => ({ ...s, [ev.node]: "active" }));
          break;
        case "node_end":
          setNodeStatuses(s => ({ ...s, [ev.node]: "done" }));
          break;
        case "plan_created":
          setPlanSteps(ev.steps);
          break;
        case "audit_complete":
          setFindings(ev.findings as AuditFinding[]);
          break;
        case "workflow_interrupted":
          setApproval({ sessionId: ev.session_id, actions: ev.pending_actions });
          break;
        case "workflow_complete":
          setSummary({ text: ev.review_summary, complete: ev.optimization_complete });
          break;
      }
    }
  }, [pushEvent]);

  const handleRun = async () => {
    if (!goal.trim() || running) return;
    saved.current = null;
    setRunning(true);
    setEvents([]);
    setPlanSteps([]);
    setFindings([]);
    setApproval(null);
    setSummary(null);
    setSelectedApprovals(new Set());
    setNodeStatuses(IDLE_NODES);
    setActiveNode(null);

    try {
      const gen = streamWorkflow(goal, dryRun, undefined, requireApproval);
      await processEvents(gen);
    } catch (err) {
      pushEvent({ type: "error", error: String(err) });
    } finally {
      setRunning(false);
      setActiveNode(null);
    }
  };

  const handleResume = async (decision: "approve-all" | "approve-selected" | "reject-all") => {
    if (!approval) return;
    const approvedIds =
      decision === "approve-all"      ? approval.actions.map(a => a.action_id) :
      decision === "approve-selected" ? [...selectedApprovals] : [];
    const rejectedIds = approval.actions
      .filter(a => !approvedIds.includes(a.action_id))
      .map(a => a.action_id);

    setApproval(null);
    setRunning(true);
    try {
      const gen = resumeWorkflow(approval.sessionId, approvedIds, rejectedIds);
      await processEvents(gen);
    } catch (err) {
      pushEvent({ type: "error", error: String(err) });
    } finally {
      setRunning(false);
      setActiveNode(null);
    }
  };

  const toggleApproval = (id: string) => {
    setSelectedApprovals(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  return (
    <div className="grid grid-cols-[300px_1fr] gap-4 h-full">
      {/* ── Left panel ─────────────────────────────────────────────────── */}
      <div className="flex flex-col gap-4">
        {/* Restored banner */}
        {isRestored && !running && (
          <div className="flex items-center justify-between px-3 py-2 bg-indigo-950/60 border border-indigo-700/50 rounded-lg text-xs text-indigo-300">
            <span>↩ Restored from previous session</span>
            <button
              onClick={handleClear}
              className="text-indigo-400 hover:text-white underline underline-offset-2"
            >
              Clear
            </button>
          </div>
        )}

        {/* Goal input */}
        <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Optimization Goal</h2>
          <textarea
            value={goal}
            onChange={e => setGoal(e.target.value)}
            placeholder="e.g. Reduce CPA across all active campaigns by 15% while maintaining current pacing..."
            rows={4}
            className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm text-gray-200 placeholder-gray-500 resize-none focus:outline-none focus:border-indigo-500"
            disabled={running}
          />
          <div className="flex items-center gap-3 mt-3">
            <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
              <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} className="accent-indigo-500" disabled={running} />
              Dry run
            </label>
            <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
              <input type="checkbox" checked={requireApproval} onChange={e => setRequireApproval(e.target.checked)} className="accent-amber-500" disabled={running} />
              Require approval
            </label>
          </div>
          <button
            onClick={handleRun}
            disabled={running || !goal.trim()}
            className="mt-3 w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium py-2 rounded transition-colors"
          >
            {running ? "Running…" : "Run Workflow"}
          </button>
        </div>

        {/* Node pipeline visualization */}
        <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-300 mb-3">Pipeline</h2>
          <div className="flex flex-col gap-2">
            {NODE_ORDER.map((node, i) => {
              const status = nodeStatuses[node];
              const isActive = status === "active";
              const isDone = status === "done";
              return (
                <div key={node} className="flex items-center gap-2">
                  <div className={`
                    flex-1 flex items-center gap-2 px-3 py-2 rounded border text-xs font-medium transition-all
                    ${isActive ? NODE_COLORS[node] + " animate-pulse" : isDone ? "bg-gray-800 border-gray-600 text-gray-400" : "bg-gray-800/50 border-gray-700/50 text-gray-600"}
                  `}>
                    <span className={`w-2 h-2 rounded-full ${isActive ? "bg-current" : isDone ? "bg-emerald-500" : "bg-gray-600"}`} />
                    {NODE_LABELS[node]}
                  </div>
                  {i < NODE_ORDER.length - 1 && (
                    <div className="text-gray-600 text-xs self-end pb-2 ml-[-6px]">↓</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Plan steps */}
        {planSteps.length > 0 && (
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4 flex-1 overflow-auto">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">Plan Steps</h2>
            <div className="flex flex-col gap-2">
              {planSteps.map(step => (
                <div key={step.step_id} className="flex items-start gap-2 text-xs">
                  <span className={`mt-0.5 ${step.status === "completed" ? "text-emerald-400" : step.status === "in_progress" ? "text-amber-400" : "text-gray-500"}`}>
                    {step.status === "completed" ? "✓" : step.status === "in_progress" ? "→" : "○"}
                  </span>
                  <div>
                    <div className={`font-medium ${step.status === "completed" ? "text-gray-400 line-through" : "text-gray-300"}`}>
                      {step.title}
                    </div>
                    <div className="text-gray-500">{step.description}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Right panel ─────────────────────────────────────────────────── */}
      <div className="flex flex-col gap-4 min-h-0">
        {/* Approval gate */}
        {approval && (
          <div className="bg-amber-950/40 border border-amber-600 rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-amber-300 font-semibold text-sm">
                Review &amp; Approve — {approval.actions.length} action(s) pending
              </h3>
              <div className="flex gap-2">
                <button onClick={() => handleResume("approve-all")} className="px-3 py-1 bg-emerald-700 hover:bg-emerald-600 text-white text-xs rounded">
                  Approve All
                </button>
                <button onClick={() => handleResume("approve-selected")} disabled={selectedApprovals.size === 0} className="px-3 py-1 bg-amber-700 hover:bg-amber-600 disabled:bg-gray-700 disabled:text-gray-500 text-white text-xs rounded">
                  Approve Selected ({selectedApprovals.size})
                </button>
                <button onClick={() => handleResume("reject-all")} className="px-3 py-1 bg-red-800 hover:bg-red-700 text-white text-xs rounded">
                  Reject All
                </button>
              </div>
            </div>
            <div className="flex flex-col gap-2">
              {approval.actions.map(action => (
                <label key={action.action_id} className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedApprovals.has(action.action_id)}
                    onChange={() => toggleApproval(action.action_id)}
                    className="mt-1 accent-amber-500"
                  />
                  <div className="text-xs flex-1">
                    <div className="flex items-center gap-2 font-medium text-amber-200">
                      <span className="font-mono bg-gray-800 px-1 rounded">{action.action_type}</span>
                      <span className="text-gray-400">on</span>
                      <span className="font-mono text-gray-300">{action.campaign_id}</span>
                      {action.approval_required && (
                        <span className="px-1.5 py-0.5 text-[10px] bg-red-500/20 text-red-400 border border-red-500/30 rounded">policy gate</span>
                      )}
                    </div>
                    <div className="text-gray-400 mt-1">{action.rationale}</div>
                    <div className="text-gray-500 mt-0.5">
                      {Object.entries(action.params).map(([k, v]) => (
                        <span key={k} className="mr-2">{k}: <span className="text-gray-300">{String(v)}</span></span>
                      ))}
                    </div>
                  </div>
                </label>
              ))}
            </div>
          </div>
        )}

        {/* Summary */}
        {summary && (
          <div className={`border rounded-lg p-4 text-sm ${summary.complete ? "bg-emerald-950/30 border-emerald-700" : "bg-amber-950/30 border-amber-700"}`}>
            <div className="flex items-center gap-2 mb-1">
              <span className={summary.complete ? "text-emerald-400" : "text-amber-400"}>
                {summary.complete ? "✓ Optimization Complete" : "↻ Iteration Needed"}
              </span>
            </div>
            <p className="text-gray-300">{summary.text}</p>
          </div>
        )}

        {/* Audit findings (shown when non-empty) */}
        {findings.length > 0 && (
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-300 mb-2">Audit Findings</h3>
            <div className="flex flex-col gap-1">
              {findings.map(f => (
                <div key={f.finding_id} className="flex items-start gap-2 text-xs">
                  <span className={`font-semibold uppercase w-16 shrink-0 ${SEVERITY_COLORS[f.severity]}`}>
                    {f.severity}
                  </span>
                  <span className="text-gray-400">{f.finding}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Event log */}
        <div
          ref={logRef}
          className="flex-1 bg-gray-950 border border-gray-800 rounded-lg p-4 overflow-y-auto font-mono text-xs min-h-0"
        >
          {events.length === 0 && !running && (
            <p className="text-gray-600">Enter an optimization goal and click Run Workflow to start the multi-agent pipeline.</p>
          )}
          {events.map((ev, i) => (
            <EventRow key={i} ev={ev} />
          ))}
          {running && activeNode && (
            <div className="flex items-center gap-2 text-gray-500 mt-1">
              <span className="animate-spin">⟳</span>
              <span>{NODE_LABELS[activeNode]} running…</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Event row renderer ────────────────────────────────────────────────────────

function EventRow({ ev }: { ev: WorkflowEvent }) {
  switch (ev.type) {
    case "workflow_start":
      return <LogLine color="text-indigo-400" icon="▶" text={`Workflow started — session ${ev.session_id.slice(0, 16)}`} />;
    case "node_start":
      return <LogLine color="text-gray-500" icon="→" text={`${NODE_LABELS[ev.node]} started`} />;
    case "node_end":
      return <LogLine color="text-gray-600" icon="✓" text={`${NODE_LABELS[ev.node]} done`} />;
    case "plan_created":
      return <LogLine color="text-indigo-300" icon="📋" text={`Plan: "${ev.title}" (${ev.step_count} steps)`} />;
    case "metrics_fetched":
      return (
        <LogLine
          color="text-cyan-400" icon="📊"
          text={`${ev.campaign_name} — pacing=${ev.pacing_rate?.toFixed(2)} spend=$${ev.spend_today_usd?.toFixed(0)} CPA=$${ev.cpa_usd?.toFixed(2) ?? "—"}`}
        />
      );
    case "rag_retrieved":
      return <LogLine color="text-cyan-600" icon="🔍" text={`RAG: ${ev.result_count} results from [${ev.sources.join(", ")}]`} />;
    case "optimizer_skipped":
      return <LogLine color="text-gray-500" icon="—" text={`Optimizer skipped: ${ev.reason}`} />;
    case "actions_proposed":
      return <LogLine color="text-violet-300" icon="💡" text={`${ev.count} action(s) proposed`} />;
    case "audit_skipped":
      return <LogLine color="text-gray-500" icon="—" text={`Audit skipped: ${ev.reason}`} />;
    case "action_approved":
      return <LogLine color="text-emerald-400" icon="✓" text={`Approved: ${ev.action_type} (${ev.action_id.slice(0, 10)})`} />;
    case "action_blocked":
      return <LogLine color="text-red-400" icon="✗" text={`Blocked: ${ev.action_type} — ${ev.reason}`} />;
    case "action_pending_approval":
      return <LogLine color="text-amber-300" icon="⏸" text={`Pending approval: ${ev.action_type} — ${ev.finding}`} />;
    case "audit_complete":
      return (
        <LogLine
          color="text-amber-400" icon="⚖"
          text={`Audit: ${ev.approved} approved / ${ev.blocked} blocked / ${ev.pending_approval} pending`}
        />
      );
    case "action_executed":
      return (
        <LogLine
          color={ev.status === "failed" ? "text-red-400" : "text-emerald-400"} icon="⚡"
          text={`Executed: ${ev.action_type} on ${ev.campaign_id} → ${ev.status}${ev.dry_run ? " [dry-run]" : ""}`}
        />
      );
    case "optimizer_fallback":
      return (
        <LogLine
          color="text-amber-400" icon="⚡"
          text={`Optimizer fallback → baseline (${ev.action_count} actions): ${ev.reason}`}
        />
      );
    case "auditor_fallback":
      return <LogLine color="text-amber-400" icon="⚡" text={`Auditor fallback → auto-approve: ${ev.reason}`} />;
    case "action_gated":
      return (
        <LogLine
          color="text-orange-400" icon="🛡"
          text={`Gated: ${ev.action_type} (${ev.action_id.slice(0, 10)}) — ${ev.reasons.join("; ")}`}
        />
      );
    case "action_passed_gate":
      return <LogLine color="text-emerald-600" icon="✓" text={`Gate passed: ${ev.action_type} (${ev.action_id.slice(0, 10)})`} />;
    case "gatekeeper_complete":
      return (
        <LogLine
          color="text-orange-300" icon="🛡"
          text={`Gatekeeper: ${ev.forwarded} forwarded / ${ev.gated} gated${ev.dry_run ? " [dry-run]" : ""}`}
        />
      );
    case "review_complete":
      return (
        <LogLine
          color="text-rose-300" icon="✦"
          text={`Review: ${ev.steps_completed}/${ev.steps_total} steps — ${ev.optimization_complete ? "complete" : "needs iteration"}`}
        />
      );
    case "workflow_interrupted":
      return <LogLine color="text-amber-300" icon="⏸" text={`Workflow paused — ${ev.pending_actions.length} action(s) awaiting approval`} />;
    case "workflow_complete":
      return <LogLine color="text-emerald-300" icon="★" text={`Workflow complete — ${ev.actions_executed} executed / ${ev.actions_blocked} blocked`} />;
    case "workflow_resumed":
      return <LogLine color="text-indigo-300" icon="▶" text={`Resumed — ${ev.approved} approved, ${ev.rejected} rejected`} />;
    case "error":
      return <LogLine color="text-red-400" icon="!" text={`Error: ${ev.error}`} />;
    default:
      return null;
  }
}

function LogLine({ color, icon, text }: { color: string; icon: string; text: string }) {
  return (
    <div className={`flex items-start gap-2 py-0.5 ${color}`}>
      <span className="shrink-0 w-4 text-center">{icon}</span>
      <span className="text-gray-300 break-all">{text}</span>
    </div>
  );
}

"use client";
import { useState } from "react";
import type { AuditLog } from "@/lib/types";
import { statusColor, relTime, cn } from "@/lib/utils";
import { ChevronDown, ChevronRight, CheckCircle, X, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";

const ACTION_ICONS: Record<string, string> = {
  update_bid_modifier: "⚡",
  update_budget: "💰",
  pause_campaign: "⏸",
  update_targeting: "🎯",
  update_supply_sources: "🏗",
  route_creative: "🎨",
  rollback: "↩",
};

export function AuditLogView({ initialLogs }: { initialLogs: AuditLog[] }) {
  const [logs, setLogs] = useState(initialLogs);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState<string | null>(null);

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const n = new Set(prev);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  };

  const refresh = async () => {
    try {
      const updated = await api.audit.list();
      setLogs(updated);
    } catch {}
  };

  const handleApprove = async (id: string) => {
    setLoading(id);
    try {
      await api.audit.approve(id);
      await refresh();
    } finally {
      setLoading(null);
    }
  };

  const handleReject = async (id: string) => {
    setLoading(id);
    try {
      await api.audit.reject(id);
      await refresh();
    } finally {
      setLoading(null);
    }
  };

  const handleRollback = async (id: string) => {
    setLoading(id);
    try {
      await api.audit.rollback(id);
      await refresh();
    } finally {
      setLoading(null);
    }
  };

  const pending = logs.filter((l) => l.status === "pending_approval");
  const rest = logs.filter((l) => l.status !== "pending_approval");

  return (
    <div className="space-y-4">
      {pending.length > 0 && (
        <div className="rounded-xl border border-yellow-500/30 bg-yellow-500/5 overflow-hidden">
          <div className="px-5 py-3 border-b border-yellow-500/20">
            <h3 className="text-sm font-semibold text-yellow-300">
              {pending.length} Action{pending.length > 1 ? "s" : ""} Awaiting Approval
            </h3>
          </div>
          <div className="divide-y divide-yellow-500/10">
            {pending.map((log) => (
              <LogRow
                key={log.id}
                log={log}
                isExpanded={expanded.has(log.id)}
                onToggle={() => toggleExpand(log.id)}
                onApprove={() => handleApprove(log.id)}
                onReject={() => handleReject(log.id)}
                onRollback={() => handleRollback(log.id)}
                isLoading={loading === log.id}
              />
            ))}
          </div>
        </div>
      )}

      <div className="rounded-xl border border-gray-800 overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-800">
          <h3 className="text-sm font-semibold text-white">Action History</h3>
        </div>
        <div className="divide-y divide-gray-800/50">
          {rest.length === 0 && (
            <div className="px-5 py-10 text-center text-gray-600 text-sm">
              No agent actions yet. Run the agent console to see actions here.
            </div>
          )}
          {rest.map((log) => (
            <LogRow
              key={log.id}
              log={log}
              isExpanded={expanded.has(log.id)}
              onToggle={() => toggleExpand(log.id)}
              onApprove={() => handleApprove(log.id)}
              onReject={() => handleReject(log.id)}
              onRollback={() => handleRollback(log.id)}
              isLoading={loading === log.id}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function LogRow({
  log,
  isExpanded,
  onToggle,
  onApprove,
  onReject,
  onRollback,
  isLoading,
}: {
  log: AuditLog;
  isExpanded: boolean;
  onToggle: () => void;
  onApprove: () => void;
  onReject: () => void;
  onRollback: () => void;
  isLoading: boolean;
}) {
  const icon = ACTION_ICONS[log.action_type] || "🔧";

  return (
    <div className={cn("transition-colors", isExpanded ? "bg-gray-800/20" : "hover:bg-gray-800/10")}>
      <button onClick={onToggle} className="w-full px-5 py-3 flex items-start gap-3 text-left">
        <span className="text-base mt-0.5 shrink-0">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-white">{log.action_type.replace(/_/g, " ")}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${statusColor(log.status)}`}>
              {log.status.replace(/_/g, " ")}
            </span>
            {log.is_dry_run && <span className="text-xs text-blue-400 px-1.5 py-0.5 rounded bg-blue-400/10">[dry run]</span>}
            {log.requires_approval && log.status === "pending_approval" && (
              <span className="text-xs text-yellow-400 px-1.5 py-0.5 rounded bg-yellow-400/10">needs approval</span>
            )}
            <span className="text-xs text-gray-600 ml-auto">{relTime(log.created_at)}</span>
          </div>
          <p className="text-xs text-gray-500 mt-0.5 truncate">
            {log.campaign_id} · {log.latency_ms}ms
          </p>
        </div>
        <span className="text-gray-600 shrink-0 mt-0.5">
          {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </span>
      </button>

      {isExpanded && (
        <div className="px-5 pb-4 space-y-3">
          {log.agent_rationale && (
            <div className="px-3 py-2 rounded-lg bg-gray-900 border border-gray-800">
              <p className="text-xs text-gray-500 font-medium mb-1">Agent Rationale</p>
              <p className="text-xs text-gray-300 leading-relaxed">{log.agent_rationale}</p>
            </div>
          )}

          {log.rag_sources?.length > 0 && (
            <div className="px-3 py-2 rounded-lg bg-gray-900 border border-gray-800">
              <p className="text-xs text-gray-500 font-medium mb-1">RAG Sources Used</p>
              <div className="flex flex-wrap gap-1">
                {log.rag_sources.map((src, i) => (
                  <span key={i} className="text-xs px-2 py-0.5 rounded bg-violet-500/10 text-violet-400 border border-violet-500/20">
                    {src}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-3 gap-2">
            {log.params_before && Object.keys(log.params_before).length > 0 && (
              <div className="px-3 py-2 rounded-lg bg-gray-900 border border-gray-800">
                <p className="text-xs text-gray-500 font-medium mb-1">Before</p>
                <pre className="text-xs text-gray-400">{JSON.stringify(log.params_before, null, 2)}</pre>
              </div>
            )}
            <div className="px-3 py-2 rounded-lg bg-gray-900 border border-gray-800">
              <p className="text-xs text-gray-500 font-medium mb-1">Requested</p>
              <pre className="text-xs text-gray-400">{JSON.stringify(log.params_requested, null, 2)}</pre>
            </div>
            {log.params_after && (
              <div className="px-3 py-2 rounded-lg bg-green-500/5 border border-green-500/20">
                <p className="text-xs text-green-500 font-medium mb-1">Applied</p>
                <pre className="text-xs text-green-400">{JSON.stringify(log.params_after, null, 2)}</pre>
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            {log.status === "pending_approval" && (
              <>
                <button
                  onClick={onApprove}
                  disabled={isLoading}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-500/15 hover:bg-green-500/25 border border-green-500/30 text-green-400 text-xs font-medium transition-colors disabled:opacity-50"
                >
                  <CheckCircle className="w-3.5 h-3.5" />
                  Approve
                </button>
                <button
                  onClick={onReject}
                  disabled={isLoading}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/15 hover:bg-red-500/25 border border-red-500/30 text-red-400 text-xs font-medium transition-colors disabled:opacity-50"
                >
                  <X className="w-3.5 h-3.5" />
                  Reject
                </button>
              </>
            )}
            {log.status === "completed" && (
              <button
                onClick={onRollback}
                disabled={isLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-orange-500/15 hover:bg-orange-500/25 border border-orange-500/30 text-orange-400 text-xs font-medium transition-colors disabled:opacity-50"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                Rollback
              </button>
            )}
            <span className="text-xs text-gray-600 font-mono">
              trace: {log.trace_id?.slice(0, 12)}...
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

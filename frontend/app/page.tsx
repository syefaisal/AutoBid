import { api } from "@/lib/api";
import { fmt$$, fmtNum, fmtPct, pacingLabel, statusColor, relTime } from "@/lib/utils";
import { StatCard } from "@/components/shared/StatCard";
import Link from "next/link";
import { ArrowRight, AlertTriangle, CheckCircle, TrendingDown, TrendingUp } from "lucide-react";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  let campaigns: Awaited<ReturnType<typeof api.campaigns.list>> = [];
  let auditLogs: Awaited<ReturnType<typeof api.audit.list>> = [];
  let experiments: Awaited<ReturnType<typeof api.experiments.list>> = [];

  try {
    [campaigns, auditLogs, experiments] = await Promise.all([
      api.campaigns.list(),
      api.audit.list(),
      api.experiments.list(),
    ]);
  } catch {
    // Backend not yet started
  }

  const active = campaigns.filter((c) => c.status === "active");
  const totalSpend = active.reduce((s, c) => s + c.spend_today_usd, 0);
  const totalBudget = active.reduce((s, c) => s + c.daily_budget_usd, 0);
  const totalImpressions = active.reduce((s, c) => s + c.impressions, 0);
  const totalConversions = active.reduce((s, c) => s + c.conversions, 0);
  const issues = active.filter((c) => c.pacing_rate < 0.75 || c.pacing_rate > 1.15);
  const pendingApprovals = auditLogs.filter((l) => l.status === "pending_approval");

  return (
    <div className="p-6 space-y-6 max-w-7xl">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Control Plane</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Bidder-adjacent AI agent · {active.length} active campaigns · RAG-grounded decisions
          </p>
        </div>
        <Link
          href="/agent"
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-500 rounded-lg text-sm font-medium text-white transition-colors"
        >
          Open Agent Console <ArrowRight className="w-4 h-4" />
        </Link>
      </div>

      {(issues.length > 0 || pendingApprovals.length > 0) && (
        <div className="space-y-2">
          {issues.map((c) => {
            const p = pacingLabel(c.pacing_rate);
            const isOver = c.pacing_rate > 1.15;
            return (
              <div key={c.id} className={`flex items-center justify-between px-4 py-3 rounded-lg border text-sm ${isOver ? "border-orange-500/30 bg-orange-500/5" : "border-yellow-500/30 bg-yellow-500/5"}`}>
                <div className="flex items-center gap-2">
                  <AlertTriangle className={`w-4 h-4 ${isOver ? "text-orange-400" : "text-yellow-400"}`} />
                  <span className="font-medium text-white">{c.name}</span>
                  <span className={p.color}>{p.label} ({(c.pacing_rate * 100).toFixed(0)}%)</span>
                </div>
                <Link href="/agent" className="text-violet-400 hover:text-violet-300 flex items-center gap-1 text-xs">
                  Ask agent <ArrowRight className="w-3 h-3" />
                </Link>
              </div>
            );
          })}
          {pendingApprovals.length > 0 && (
            <div className="flex items-center justify-between px-4 py-3 rounded-lg border border-violet-500/30 bg-violet-500/5 text-sm">
              <div className="flex items-center gap-2">
                <CheckCircle className="w-4 h-4 text-violet-400" />
                <span className="font-medium text-white">{pendingApprovals.length} action{pendingApprovals.length > 1 ? "s" : ""} awaiting approval</span>
              </div>
              <Link href="/audit" className="text-violet-400 hover:text-violet-300 flex items-center gap-1 text-xs">
                Review <ArrowRight className="w-3 h-3" />
              </Link>
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Today's Spend" value={fmt$$(totalSpend)} sub={`of ${fmt$$(totalBudget)} budget`} />
        <StatCard label="Impressions" value={fmtNum(totalImpressions)} />
        <StatCard label="Conversions" value={fmtNum(totalConversions)} highlight="green" />
        <StatCard
          label="Pending Approvals"
          value={pendingApprovals.length}
          sub="agent actions queued"
          highlight={pendingApprovals.length > 0 ? "yellow" : "none"}
        />
      </div>

      <div className="rounded-xl border border-gray-800 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
          <h2 className="font-semibold text-white">Active Campaigns</h2>
          <Link href="/campaigns" className="text-xs text-violet-400 hover:text-violet-300">View all →</Link>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
                <th className="px-5 py-3 font-medium">Campaign</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium text-right">Pacing</th>
                <th className="px-4 py-3 font-medium text-right">Spend</th>
                <th className="px-4 py-3 font-medium text-right">CPA</th>
                <th className="px-4 py-3 font-medium text-right">Bid Mod</th>
                <th className="px-4 py-3 font-medium text-right">CTR</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {campaigns.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-5 py-10 text-center text-gray-600">
                    Start the backend to load campaign data
                  </td>
                </tr>
              ) : (
                campaigns.map((c) => {
                  const p = pacingLabel(c.pacing_rate);
                  return (
                    <tr key={c.id} className="hover:bg-gray-800/30 transition-colors">
                      <td className="px-5 py-3">
                        <Link href={`/campaigns/${c.id}`} className="hover:text-violet-300 transition-colors">
                          <p className="font-medium text-white">{c.name}</p>
                          <p className="text-xs text-gray-500">{c.advertiser} · {c.optimization_goal.toUpperCase()}</p>
                        </Link>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${statusColor(c.status)}`}>
                          {c.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className={`text-xs font-medium ${p.color}`}>{p.label}</span>
                        <div className="w-20 h-1 bg-gray-800 rounded-full mt-1 ml-auto">
                          <div
                            className={`h-full rounded-full ${c.pacing_rate > 1.1 ? "bg-orange-400" : c.pacing_rate < 0.8 ? "bg-yellow-400" : "bg-green-400"}`}
                            style={{ width: `${Math.min(100, c.pacing_rate * 100)}%` }}
                          />
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs">
                        <span className="text-gray-300">{fmt$$(c.spend_today_usd, 0)}</span>
                        <p className="text-gray-600">/ {fmt$$(c.daily_budget_usd, 0)}</p>
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs">
                        {c.cpa_usd ? (
                          <span className={c.cpa_usd > 40 ? "text-red-400" : "text-green-400"}>{fmt$$(c.cpa_usd, 2)}</span>
                        ) : <span className="text-gray-600">—</span>}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs">
                        <span className={c.bid_modifier !== 1 ? "text-violet-300" : "text-gray-400"}>
                          {c.bid_modifier.toFixed(2)}×
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs text-gray-400">
                        {fmtPct(c.ctr_pct, 2)}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-xl border border-gray-800 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
            <h2 className="font-semibold text-white">Recent Agent Actions</h2>
            <Link href="/audit" className="text-xs text-violet-400 hover:text-violet-300">View log →</Link>
          </div>
          <div className="divide-y divide-gray-800/50">
            {auditLogs.slice(0, 5).map((log) => (
              <div key={log.id} className="px-5 py-3 flex items-start gap-3">
                <span className="text-base mt-0.5">
                  {log.action_type === "update_bid_modifier" ? "⚡" : log.action_type === "update_budget" ? "💰" : log.action_type === "pause_campaign" ? "⏸" : log.action_type === "update_targeting" ? "🎯" : "🔧"}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm text-white font-medium">{log.action_type.replace(/_/g, " ")}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded ${statusColor(log.status)}`}>{log.status.replace(/_/g, " ")}</span>
                    {log.is_dry_run && <span className="text-xs text-blue-400">[dry run]</span>}
                    <span className="text-xs text-gray-600 ml-auto">{relTime(log.created_at)}</span>
                  </div>
                  {log.agent_rationale && (
                    <p className="text-xs text-gray-500 mt-0.5 truncate">{log.agent_rationale.slice(0, 90)}...</p>
                  )}
                </div>
              </div>
            ))}
            {auditLogs.length === 0 && (
              <div className="px-5 py-8 text-center text-gray-600 text-sm">No agent actions yet — run the agent console</div>
            )}
          </div>
        </div>

        <div className="rounded-xl border border-gray-800 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
            <h2 className="font-semibold text-white">A/B Experiments</h2>
            <Link href="/experiments" className="text-xs text-violet-400 hover:text-violet-300">View all →</Link>
          </div>
          <div className="divide-y divide-gray-800/50">
            {experiments.slice(0, 4).map((exp) => (
              <div key={exp.id} className="px-5 py-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium text-white leading-snug">{exp.name}</p>
                  <span className={`shrink-0 text-xs px-1.5 py-0.5 rounded ${statusColor(exp.status)}`}>{exp.status}</span>
                </div>
                {exp.lift_pct != null && (
                  <div className="flex items-center gap-2 mt-1.5">
                    {exp.lift_pct < 0
                      ? <TrendingDown className="w-3 h-3 text-green-400" />
                      : <TrendingUp className="w-3 h-3 text-red-400" />}
                    <span className={`text-xs font-medium ${exp.lift_pct < 0 ? "text-green-400" : "text-red-400"}`}>
                      {exp.lift_pct > 0 ? "+" : ""}{exp.lift_pct.toFixed(1)}% {exp.metric.toUpperCase()}
                    </span>
                    {exp.is_significant && <span className="text-xs text-green-500">p={exp.p_value?.toFixed(3)} ✓ significant</span>}
                  </div>
                )}
                <p className="text-xs text-gray-600 mt-0.5 line-clamp-1">{exp.hypothesis}</p>
              </div>
            ))}
            {experiments.length === 0 && (
              <div className="px-5 py-8 text-center text-gray-600 text-sm">No experiments running</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

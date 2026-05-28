import { api } from "@/lib/api";
import { fmt$$, fmtNum, fmtPct, pacingLabel, statusColor } from "@/lib/utils";
import { notFound } from "next/navigation";
import { CampaignChart } from "@/components/dashboard/CampaignChart";

export const dynamic = "force-dynamic";

export default async function CampaignDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let metrics: Awaited<ReturnType<typeof api.campaigns.metrics>> | null = null;
  let history: Awaited<ReturnType<typeof api.campaigns.history>> = [];
  try {
    [metrics, history] = await Promise.all([
      api.campaigns.metrics(id),
      api.campaigns.history(id, 24),
    ]);
  } catch {
    notFound();
  }

  if (!metrics) notFound();

  const p = pacingLabel(metrics.pacing_rate);

  return (
    <div className="p-6 space-y-6 max-w-6xl">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">{metrics.name}</h1>
          <p className="text-sm text-gray-500 mt-0.5">{metrics.advertiser} · {metrics.id}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2.5 py-1 rounded-lg font-medium ${statusColor(metrics.status)}`}>{metrics.status}</span>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-xl border border-gray-800 bg-[#111827] p-4">
          <p className="text-xs text-gray-500">Today Spend</p>
          <p className="text-2xl font-bold text-white mt-1">{fmt$$(metrics.spend_today_usd)}</p>
          <p className="text-xs text-gray-500 mt-0.5">of {fmt$$(metrics.daily_budget_usd)} · {metrics.budget_utilization_pct}% used</p>
        </div>
        <div className={`rounded-xl border p-4 ${metrics.pacing_rate < 0.75 ? "border-yellow-500/30 bg-yellow-500/5" : metrics.pacing_rate > 1.15 ? "border-orange-500/30 bg-orange-500/5" : "border-gray-800 bg-[#111827]"}`}>
          <p className="text-xs text-gray-500">Pacing</p>
          <p className={`text-2xl font-bold mt-1 ${p.color}`}>{(metrics.pacing_rate * 100).toFixed(0)}%</p>
          <p className={`text-xs mt-0.5 ${p.color}`}>{p.label}</p>
        </div>
        <div className="rounded-xl border border-gray-800 bg-[#111827] p-4">
          <p className="text-xs text-gray-500">CPA</p>
          <p className={`text-2xl font-bold mt-1 ${metrics.cpa_usd && metrics.target_cpa && metrics.cpa_usd > metrics.target_cpa ? "text-red-400" : "text-white"}`}>
            {metrics.cpa_usd ? fmt$$(metrics.cpa_usd, 2) : "—"}
          </p>
          {metrics.target_cpa && <p className="text-xs text-gray-500 mt-0.5">target {fmt$$(metrics.target_cpa, 2)}</p>}
        </div>
        <div className="rounded-xl border border-gray-800 bg-[#111827] p-4">
          <p className="text-xs text-gray-500">Effective Bid</p>
          <p className="text-2xl font-bold text-white mt-1">{fmt$$(metrics.effective_bid_cpm, 2)}</p>
          <p className="text-xs text-gray-500 mt-0.5">base {fmt$$(metrics.base_bid_cpm, 2)} × {metrics.bid_modifier.toFixed(2)}×</p>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        {[
          { label: "Impressions", value: fmtNum(metrics.impressions) },
          { label: "Clicks", value: fmtNum(metrics.clicks) },
          { label: "Conversions", value: fmtNum(metrics.conversions) },
          { label: "CTR", value: fmtPct(metrics.ctr_pct, 2) },
          { label: "CVR", value: fmtPct(metrics.cvr_pct, 2) },
        ].map((s) => (
          <div key={s.label} className="rounded-xl border border-gray-800 bg-[#111827] p-4">
            <p className="text-xs text-gray-500">{s.label}</p>
            <p className="text-xl font-bold text-white mt-1">{s.value}</p>
          </div>
        ))}
      </div>

      {history.length > 0 && (
        <div className="rounded-xl border border-gray-800 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-800">
            <h2 className="font-semibold text-white">24h Performance</h2>
          </div>
          <div className="p-4">
            <CampaignChart history={history} />
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-xl border border-gray-800 p-4">
          <h3 className="text-sm font-semibold text-white mb-3">Targeting</h3>
          <div className="space-y-2">
            {Object.entries(metrics.targeting || {}).map(([k, v]) => (
              <div key={k} className="flex items-start gap-3">
                <span className="text-xs text-gray-500 w-32 shrink-0 pt-0.5 capitalize">{k.replace(/_/g, " ")}</span>
                <div className="flex flex-wrap gap-1">
                  {Array.isArray(v) ? v.map((item, i) => (
                    <span key={i} className="text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-300">{String(item)}</span>
                  )) : (
                    <span className="text-xs text-gray-300">{String(v)}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-xl border border-gray-800 p-4">
          <h3 className="text-sm font-semibold text-white mb-3">Supply Sources</h3>
          <div className="flex flex-wrap gap-2">
            {(metrics.supply_sources || []).map((src) => (
              <span key={src} className="text-xs px-2.5 py-1 rounded-lg bg-gray-800 text-gray-300 border border-gray-700">
                {src}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

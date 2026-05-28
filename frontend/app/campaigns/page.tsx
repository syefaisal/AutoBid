import { api } from "@/lib/api";
import { fmt$$, fmtNum, fmtPct, pacingLabel, statusColor } from "@/lib/utils";
import Link from "next/link";

export const dynamic = "force-dynamic";

export default async function CampaignsPage() {
  let campaigns: Awaited<ReturnType<typeof api.campaigns.list>> = [];
  try {
    campaigns = await api.campaigns.list();
  } catch {}

  return (
    <div className="p-6 space-y-4 max-w-7xl">
      <div>
        <h1 className="text-2xl font-bold text-white">Campaigns</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {campaigns.length} campaigns across {new Set(campaigns.map((c) => c.advertiser)).size} advertisers
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4">
        {campaigns.length === 0 && (
          <div className="rounded-xl border border-gray-800 px-5 py-12 text-center text-gray-600">
            Start the backend to load campaigns
          </div>
        )}
        {campaigns.map((c) => {
          const p = pacingLabel(c.pacing_rate);
          const budgetPct = c.daily_budget_usd > 0 ? (c.spend_today_usd / c.daily_budget_usd * 100) : 0;
          return (
            <Link key={c.id} href={`/campaigns/${c.id}`}>
              <div className="rounded-xl border border-gray-800 hover:border-gray-700 bg-[#111827] hover:bg-gray-800/50 transition-all p-5">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 flex-wrap">
                      <h3 className="font-semibold text-white">{c.name}</h3>
                      <span className={`text-xs px-2 py-0.5 rounded font-medium ${statusColor(c.status)}`}>{c.status}</span>
                      <span className="text-xs text-gray-500">{c.advertiser}</span>
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs text-gray-600">Goal: {c.optimization_goal.toUpperCase()}</span>
                      <span className="text-xs text-gray-700">·</span>
                      <span className={`text-xs font-medium ${p.color}`}>{p.label} ({(c.pacing_rate * 100).toFixed(0)}%)</span>
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-sm font-medium text-white">{fmt$$(c.spend_today_usd, 0)} / {fmt$$(c.daily_budget_usd, 0)}</p>
                    <p className="text-xs text-gray-500">{budgetPct.toFixed(0)}% utilized</p>
                  </div>
                </div>

                <div className="mt-3 w-full h-1.5 bg-gray-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${budgetPct > 110 ? "bg-red-400" : budgetPct > 95 ? "bg-orange-400" : "bg-violet-500"}`}
                    style={{ width: `${Math.min(100, budgetPct)}%` }}
                  />
                </div>

                <div className="grid grid-cols-5 gap-4 mt-4 pt-3 border-t border-gray-800">
                  <div>
                    <p className="text-xs text-gray-500">Impressions</p>
                    <p className="text-sm font-medium text-white mt-0.5">{fmtNum(c.impressions)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">Clicks</p>
                    <p className="text-sm font-medium text-white mt-0.5">{fmtNum(c.clicks)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">CTR</p>
                    <p className="text-sm font-medium text-white mt-0.5">{fmtPct(c.ctr_pct, 2)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">CPA</p>
                    <p className={`text-sm font-medium mt-0.5 ${c.cpa_usd && c.cpa_usd > 40 ? "text-red-400" : "text-white"}`}>
                      {c.cpa_usd ? fmt$$(c.cpa_usd, 2) : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">Bid Modifier</p>
                    <p className={`text-sm font-medium mt-0.5 ${c.bid_modifier !== 1 ? "text-violet-300" : "text-gray-400"}`}>
                      {c.bid_modifier.toFixed(2)}×
                    </p>
                  </div>
                </div>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

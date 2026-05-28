"use client";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import type { HistoryPoint } from "@/lib/types";

export function CampaignChart({ history }: { history: HistoryPoint[] }) {
  const data = history.map((h) => ({
    hour: new Date(h.hour_ts).toLocaleTimeString("en-US", { hour: "2-digit", hour12: false }),
    spend: Number(h.spend_usd.toFixed(2)),
    impressions: Math.round(h.impressions / 1000),
    conversions: h.conversions,
    win_rate: Number((h.win_rate * 100).toFixed(1)),
  }));

  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
        <defs>
          <linearGradient id="spendGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="impGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#22d3ee" stopOpacity={0.2} />
            <stop offset="95%" stopColor="#22d3ee" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
        <XAxis dataKey="hour" tick={{ fontSize: 10, fill: "#6b7280" }} />
        <YAxis tick={{ fontSize: 10, fill: "#6b7280" }} />
        <Tooltip
          contentStyle={{ background: "#111827", border: "1px solid #374151", borderRadius: 8, fontSize: 12 }}
          labelStyle={{ color: "#9ca3af" }}
        />
        <Legend wrapperStyle={{ fontSize: 11, color: "#9ca3af" }} />
        <Area type="monotone" dataKey="spend" name="Spend ($)" stroke="#8b5cf6" fill="url(#spendGrad)" strokeWidth={2} dot={false} />
        <Area type="monotone" dataKey="impressions" name="Impressions (K)" stroke="#22d3ee" fill="url(#impGrad)" strokeWidth={2} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

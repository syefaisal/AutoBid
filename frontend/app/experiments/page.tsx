import { api } from "@/lib/api";
import { statusColor, fmt$$ } from "@/lib/utils";
import { TrendingDown, TrendingUp, CheckCircle } from "lucide-react";

export const dynamic = "force-dynamic";

export default async function ExperimentsPage() {
  let experiments: Awaited<ReturnType<typeof api.experiments.list>> = [];
  try {
    experiments = await api.experiments.list();
  } catch {}

  return (
    <div className="p-6 space-y-4 max-w-5xl">
      <div>
        <h1 className="text-2xl font-bold text-white">A/B Experiments</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Online experimentation · Agent-driven control-plane decisions · Statistical significance
        </p>
      </div>

      {experiments.length === 0 && (
        <div className="rounded-xl border border-gray-800 px-5 py-12 text-center text-gray-600">
          No experiments found — start the backend to load data
        </div>
      )}

      <div className="space-y-4">
        {experiments.map((exp) => (
          <div key={exp.id} className="rounded-xl border border-gray-800 bg-[#111827] overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-800">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="font-semibold text-white">{exp.name}</h3>
                  <p className="text-xs text-gray-500 mt-0.5">{exp.description}</p>
                </div>
                <span className={`shrink-0 text-xs px-2 py-1 rounded-lg font-medium ${statusColor(exp.status)}`}>{exp.status}</span>
              </div>
            </div>

            <div className="px-6 py-4">
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="space-y-2">
                  <p className="text-xs font-medium text-gray-400 uppercase tracking-wider">Hypothesis</p>
                  <p className="text-sm text-gray-300 leading-relaxed">{exp.hypothesis}</p>
                  <div className="flex items-center gap-2 mt-2">
                    <span className="text-xs text-gray-500">Metric:</span>
                    <span className="text-xs font-medium text-violet-300 uppercase">{exp.metric}</span>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg bg-gray-800/50 border border-gray-700 p-3">
                    <p className="text-xs text-gray-500 mb-1">Control</p>
                    <p className="text-xl font-bold text-white">
                      {exp.control_metric_value != null ? (exp.metric === "cpa" ? fmt$$(exp.control_metric_value, 2) : exp.control_metric_value.toFixed(2)) : "—"}
                    </p>
                    <p className="text-xs text-gray-600 mt-0.5">{exp.control_campaign_ids.length} campaign{exp.control_campaign_ids.length > 1 ? "s" : ""}</p>
                  </div>
                  <div className="rounded-lg bg-gray-800/50 border border-gray-700 p-3">
                    <p className="text-xs text-gray-500 mb-1">Treatment</p>
                    <p className="text-xl font-bold text-white">
                      {exp.treatment_metric_value != null ? (exp.metric === "cpa" ? fmt$$(exp.treatment_metric_value, 2) : exp.treatment_metric_value.toFixed(2)) : "—"}
                    </p>
                    <p className="text-xs text-gray-600 mt-0.5">{exp.treatment_campaign_ids.length} campaign{exp.treatment_campaign_ids.length > 1 ? "s" : ""}</p>
                  </div>
                </div>

                <div className="flex flex-col justify-center">
                  {exp.lift_pct != null ? (
                    <div className="text-center">
                      <div className="flex items-center justify-center gap-2 mb-2">
                        {exp.lift_pct < 0
                          ? <TrendingDown className="w-5 h-5 text-green-400" />
                          : <TrendingUp className="w-5 h-5 text-red-400" />}
                        <span className={`text-3xl font-bold ${exp.lift_pct < 0 ? "text-green-400" : "text-red-400"}`}>
                          {exp.lift_pct > 0 ? "+" : ""}{exp.lift_pct.toFixed(1)}%
                        </span>
                      </div>
                      <p className="text-sm text-gray-400">
                        {exp.lift_pct < 0 ? "Improvement" : "Degradation"} in {exp.metric.toUpperCase()}
                      </p>
                      {exp.p_value != null && (
                        <div className="flex items-center justify-center gap-1.5 mt-2">
                          {exp.is_significant && <CheckCircle className="w-3.5 h-3.5 text-green-500" />}
                          <span className={`text-xs ${exp.is_significant ? "text-green-500" : "text-gray-500"}`}>
                            p = {exp.p_value.toFixed(3)} {exp.is_significant ? "(significant)" : "(not significant)"}
                          </span>
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="text-sm text-gray-600 text-center">Collecting data...</p>
                  )}
                </div>
              </div>
            </div>

            <div className="px-6 py-3 border-t border-gray-800 flex items-center gap-4 text-xs text-gray-600">
              <span>Started: {exp.start_date ? new Date(exp.start_date).toLocaleDateString() : "—"}</span>
              {exp.end_date && <span>Ended: {new Date(exp.end_date).toLocaleDateString()}</span>}
              <span>ID: {exp.id}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

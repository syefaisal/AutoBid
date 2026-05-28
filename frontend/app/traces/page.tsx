import { api } from "@/lib/api";
import { fmtMs, relTime, statusColor } from "@/lib/utils";
import Link from "next/link";

export const dynamic = "force-dynamic";

export default async function TracesPage() {
  let traces: Awaited<ReturnType<typeof api.traces.list>> = [];
  try {
    traces = await api.traces.list();
  } catch {}

  return (
    <div className="p-6 space-y-4 max-w-5xl">
      <div>
        <h1 className="text-2xl font-bold text-white">Distributed Traces</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          End-to-end observability · Agent loop · RAG retrieval · Tool execution · Latency breakdown
        </p>
      </div>

      <div className="rounded-xl border border-gray-800 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
                <th className="px-5 py-3 font-medium">Root Span</th>
                <th className="px-4 py-3 font-medium">Service</th>
                <th className="px-4 py-3 font-medium text-right">Duration</th>
                <th className="px-4 py-3 font-medium text-right">Spans</th>
                <th className="px-4 py-3 font-medium text-right">Status</th>
                <th className="px-4 py-3 font-medium text-right">When</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {traces.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-10 text-center text-gray-600">
                    No traces yet — run the agent to generate trace data
                  </td>
                </tr>
              )}
              {traces.map((t) => (
                <tr key={t.trace_id} className="hover:bg-gray-800/30 transition-colors">
                  <td className="px-5 py-3">
                    <Link href={`/traces/${t.trace_id}`} className="hover:text-violet-300 transition-colors">
                      <span className="font-medium text-white">{t.root_span}</span>
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs px-2 py-0.5 rounded bg-violet-500/10 text-violet-400 border border-violet-500/20">
                      {t.service}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-xs text-gray-300">
                    {fmtMs(t.duration_ms)}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-400 text-xs">{t.span_count}</td>
                  <td className="px-4 py-3 text-right">
                    <span className={`text-xs px-1.5 py-0.5 rounded ${statusColor(t.status)}`}>{t.status}</span>
                  </td>
                  <td className="px-4 py-3 text-right text-xs text-gray-600">
                    {relTime(new Date(t.start_time_ms).toISOString())}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

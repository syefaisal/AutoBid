import { api } from "@/lib/api";
import { fmtMs, statusColor } from "@/lib/utils";
import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export const dynamic = "force-dynamic";

export default async function TraceDetailPage({ params }: { params: Promise<{ traceId: string }> }) {
  const { traceId } = await params;
  let trace: Awaited<ReturnType<typeof api.traces.get>> | null = null;
  try {
    trace = await api.traces.get(traceId);
  } catch {
    notFound();
  }
  if (!trace || !trace.spans.length) notFound();

  const minTime = Math.min(...trace.spans.map((s) => s.start_time_ms));
  const maxTime = Math.max(...trace.spans.map((s) => s.end_time_ms || s.start_time_ms));
  const totalDuration = maxTime - minTime;

  return (
    <div className="p-6 space-y-4 max-w-5xl">
      <div className="flex items-center gap-3">
        <Link href="/traces" className="text-gray-500 hover:text-gray-300 transition-colors">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <div>
          <h1 className="text-xl font-bold text-white">Trace: {traceId.slice(0, 16)}...</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {trace.spans.length} spans · {fmtMs(totalDuration)}
          </p>
        </div>
      </div>

      <div className="rounded-xl border border-gray-800 overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-800 grid grid-cols-[200px_1fr_80px_60px] gap-4 text-xs text-gray-500 font-medium">
          <span>Span</span>
          <span>Timeline</span>
          <span className="text-right">Duration</span>
          <span className="text-right">Status</span>
        </div>

        <div className="divide-y divide-gray-800/50">
          {trace.spans.map((span) => {
            const left = totalDuration > 0 ? ((span.start_time_ms - minTime) / totalDuration) * 100 : 0;
            const width = totalDuration > 0 && span.duration_ms ? (span.duration_ms / totalDuration) * 100 : 2;
            const depth = span.parent_span_id ? 1 : 0;
            const isError = span.status === "error";

            return (
              <div key={span.span_id} className="px-5 py-2.5 grid grid-cols-[200px_1fr_80px_60px] gap-4 items-center hover:bg-gray-800/20 transition-colors">
                <div style={{ paddingLeft: depth * 16 }}>
                  <p className="text-xs font-medium text-white truncate">{span.name}</p>
                  <p className="text-[10px] text-gray-600">{span.service}</p>
                </div>

                <div className="relative h-6 flex items-center">
                  <div className="absolute inset-0 flex items-center">
                    <div className="w-full h-px bg-gray-800" />
                  </div>
                  <div
                    className={`absolute h-4 rounded-sm ${isError ? "bg-red-500/60" : span.service === "autobid-rag" ? "bg-cyan-500/50" : span.service === "autobid-tools" ? "bg-green-500/50" : "bg-violet-500/50"}`}
                    style={{ left: `${left}%`, width: `${Math.max(width, 1)}%` }}
                  />
                </div>

                <p className="text-right font-mono text-xs text-gray-400">{fmtMs(span.duration_ms)}</p>
                <div className="text-right">
                  <span className={`text-xs px-1.5 py-0.5 rounded ${statusColor(span.status)}`}>{span.status}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-6 text-xs text-gray-500">
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-2 rounded-sm bg-violet-500/50" />
          <span>Agent</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-2 rounded-sm bg-cyan-500/50" />
          <span>RAG</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-2 rounded-sm bg-green-500/50" />
          <span>Tool execution</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-2 rounded-sm bg-red-500/60" />
          <span>Error</span>
        </div>
      </div>

      {/* Span attributes */}
      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-white">Span Details</h3>
        {trace.spans.map((span) => {
          if (!Object.keys(span.attributes).length && !span.events.length) return null;
          return (
            <div key={span.span_id} className="rounded-lg border border-gray-800 p-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-medium text-white">{span.name}</span>
                <span className="text-[10px] text-gray-600 font-mono">{span.span_id}</span>
              </div>
              {Object.keys(span.attributes).length > 0 && (
                <div className="grid grid-cols-2 gap-1">
                  {Object.entries(span.attributes).map(([k, v]) => (
                    <div key={k} className="flex items-start gap-2">
                      <span className="text-[10px] text-gray-500 shrink-0 w-28">{k}</span>
                      <span className="text-[10px] text-gray-300 truncate">{String(v).slice(0, 80)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

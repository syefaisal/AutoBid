"use client";
import { useState, useRef, useCallback, useEffect } from "react";
import { streamAgentRun } from "@/lib/api";
import type { AgentEvent, Campaign } from "@/lib/types";
import { fmtMs, statusColor, cn } from "@/lib/utils";
import { Send, Loader2, ToggleLeft, ToggleRight, ChevronDown, ChevronRight, Bot, User, Zap, BookOpen, CheckCircle, AlertCircle, Clock } from "lucide-react";

interface Message {
  role: "user" | "assistant" | "tool_call" | "tool_result" | "system";
  content: string;
  toolName?: string;
  toolInput?: Record<string, unknown>;
  toolResult?: Record<string, unknown>;
  timestamp: Date;
}

const SAMPLE_QUERIES = [
  "Analyze all active campaigns and fix any pacing issues",
  "The Nike retargeting campaign is under-delivering — diagnose and fix",
  "Optimize CPA across all campaigns and recommend bid changes",
  "Check Netflix campaign for over-pacing and suggest corrective actions",
  "Run a full health check on Whole Foods campaign",
];

export function AgentConsole({ campaigns }: { campaigns: Campaign[] }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isDryRun, setIsDryRun] = useState(true);
  const [isRunning, setIsRunning] = useState(false);
  const [expandedTools, setExpandedTools] = useState<Set<number>>(new Set());
  const [sessionMeta, setSessionMeta] = useState<{ latency?: number; tools?: number; rag?: number; sessionId?: string; traceId?: string } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  useEffect(() => { scrollToBottom(); }, [messages, scrollToBottom]);

  const appendText = useCallback((text: string) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last?.role === "assistant") {
        return [...prev.slice(0, -1), { ...last, content: last.content + text }];
      }
      return [...prev, { role: "assistant", content: text, timestamp: new Date() }];
    });
  }, []);

  const run = useCallback(async (query: string) => {
    if (!query.trim() || isRunning) return;
    setIsRunning(true);
    setSessionMeta(null);

    setMessages((prev) => [
      ...prev,
      { role: "user", content: query, timestamp: new Date() },
    ]);

    try {
      for await (const event of streamAgentRun(query, isDryRun)) {
        switch (event.type) {
          case "text_delta":
            appendText(event.text);
            break;
          case "tool_call":
            setMessages((prev) => [
              ...prev,
              {
                role: "tool_call",
                content: event.tool_name,
                toolName: event.tool_name,
                toolInput: event.tool_input,
                timestamp: new Date(),
              },
            ]);
            break;
          case "tool_result":
            setMessages((prev) => [
              ...prev,
              {
                role: "tool_result",
                content: event.tool_name,
                toolName: event.tool_name,
                toolResult: event.result,
                timestamp: new Date(),
              },
            ]);
            break;
          case "done":
            setSessionMeta({
              latency: event.total_latency_ms,
              tools: event.tool_calls,
              rag: event.rag_retrievals,
              sessionId: event.session_id,
              traceId: event.trace_id,
            });
            break;
          case "error":
            setMessages((prev) => [
              ...prev,
              { role: "system", content: `Error: ${event.error}`, timestamp: new Date() },
            ]);
            break;
        }
      }
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { role: "system", content: `Connection error: ${e}`, timestamp: new Date() },
      ]);
    } finally {
      setIsRunning(false);
    }
  }, [isDryRun, isRunning, appendText]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    run(input.trim());
    setInput("");
  };

  const toggleTool = (idx: number) => {
    setExpandedTools((prev) => {
      const n = new Set(prev);
      n.has(idx) ? n.delete(idx) : n.add(idx);
      return n;
    });
  };

  return (
    <div className="h-full flex">
      {/* Left: Chat */}
      <div className="flex-1 flex flex-col border-r border-gray-800">
        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full gap-6 text-center">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center">
                <Bot className="w-7 h-7 text-white" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-white">AutoBid Agent</h3>
                <p className="text-sm text-gray-500 mt-1 max-w-xs">
                  Ask me to analyze campaigns, fix pacing issues, optimize bids, or route inventory.
                  I&apos;ll retrieve policy context and take safe, audited actions.
                </p>
              </div>
              <div className="grid grid-cols-1 gap-2 w-full max-w-md">
                {SAMPLE_QUERIES.map((q) => (
                  <button
                    key={q}
                    onClick={() => { setInput(q); textareaRef.current?.focus(); }}
                    className="text-left px-4 py-2.5 rounded-lg border border-gray-700 hover:border-violet-500/50 hover:bg-violet-500/5 text-sm text-gray-400 hover:text-gray-200 transition-all"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, idx) => {
            if (msg.role === "user") {
              return (
                <div key={idx} className="flex gap-3 justify-end">
                  <div className="max-w-lg bg-violet-600/20 border border-violet-500/30 rounded-2xl rounded-tr-sm px-4 py-3">
                    <p className="text-sm text-gray-100">{msg.content}</p>
                  </div>
                  <div className="w-7 h-7 rounded-full bg-gray-700 flex items-center justify-center shrink-0 mt-0.5">
                    <User className="w-3.5 h-3.5 text-gray-300" />
                  </div>
                </div>
              );
            }

            if (msg.role === "assistant") {
              return (
                <div key={idx} className="flex gap-3">
                  <div className="w-7 h-7 rounded-full bg-violet-600 flex items-center justify-center shrink-0 mt-0.5">
                    <Bot className="w-3.5 h-3.5 text-white" />
                  </div>
                  <div className="max-w-2xl flex-1">
                    <p className={cn("text-sm text-gray-200 leading-relaxed whitespace-pre-wrap", isRunning && idx === messages.length - 1 && "typing-cursor")}>
                      {msg.content}
                    </p>
                  </div>
                </div>
              );
            }

            if (msg.role === "tool_call") {
              const isExpanded = expandedTools.has(idx);
              const toolIcon = msg.toolName === "retrieve_policy" ? <BookOpen className="w-3.5 h-3.5" /> :
                               msg.toolName === "get_campaign_metrics" ? <Zap className="w-3.5 h-3.5" /> :
                               <CheckCircle className="w-3.5 h-3.5" />;
              return (
                <div key={idx} className="flex gap-3">
                  <div className="w-7 shrink-0" />
                  <div className="flex-1 max-w-2xl">
                    <button
                      onClick={() => toggleTool(idx)}
                      className="flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-700 bg-gray-800/50 hover:bg-gray-800 transition-colors text-xs text-gray-400 w-full text-left"
                    >
                      <span className="text-violet-400">{toolIcon}</span>
                      <span className="text-violet-300 font-medium font-mono">{msg.toolName}</span>
                      {msg.toolInput?.campaign_id != null && (
                        <span className="text-gray-500">· {String(msg.toolInput.campaign_id).slice(0, 12)}...</span>
                      )}
                      {msg.toolInput?.query != null && (
                        <span className="text-gray-500 truncate">· &quot;{String(msg.toolInput.query).slice(0, 40)}&quot;</span>
                      )}
                      <span className="ml-auto text-gray-600">
                        {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      </span>
                    </button>
                    {isExpanded && (
                      <pre className="mt-1 px-3 py-2 rounded-lg bg-gray-900 text-xs text-gray-400 overflow-x-auto border border-gray-800">
                        {JSON.stringify(msg.toolInput, null, 2)}
                      </pre>
                    )}
                  </div>
                </div>
              );
            }

            if (msg.role === "tool_result") {
              const isExpanded = expandedTools.has(idx);
              const hasError = "error" in (msg.toolResult || {});
              const status = (msg.toolResult as Record<string, unknown>)?.status as string;
              return (
                <div key={idx} className="flex gap-3">
                  <div className="w-7 shrink-0" />
                  <div className="flex-1 max-w-2xl">
                    <button
                      onClick={() => toggleTool(idx)}
                      className="flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-700/50 bg-gray-900/50 hover:bg-gray-900 transition-colors text-xs text-gray-500 w-full text-left"
                    >
                      {hasError ? (
                        <AlertCircle className="w-3.5 h-3.5 text-red-400" />
                      ) : (
                        <CheckCircle className="w-3.5 h-3.5 text-green-400" />
                      )}
                      <span className="font-mono text-gray-400">{msg.toolName} →</span>
                      {status && (
                        <span className={`px-1.5 py-0.5 rounded text-xs ${statusColor(status)}`}>
                          {status.replace(/_/g, " ")}
                        </span>
                      )}
                      {isDryRun && (msg.toolResult as Record<string, unknown>)?.dry_run != null && (
                        <span className="text-blue-400 text-xs">[dry run]</span>
                      )}
                      <span className="ml-auto text-gray-700">
                        {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      </span>
                    </button>
                    {isExpanded && (
                      <pre className="mt-1 px-3 py-2 rounded-lg bg-gray-900 text-xs text-gray-400 overflow-x-auto border border-gray-800 max-h-48">
                        {JSON.stringify(msg.toolResult, null, 2)}
                      </pre>
                    )}
                  </div>
                </div>
              );
            }

            if (msg.role === "system") {
              return (
                <div key={idx} className="flex gap-3">
                  <div className="w-7 shrink-0" />
                  <div className="px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 text-xs text-red-400">
                    {msg.content}
                  </div>
                </div>
              );
            }
            return null;
          })}

          {isRunning && messages[messages.length - 1]?.role !== "assistant" && (
            <div className="flex gap-3">
              <div className="w-7 h-7 rounded-full bg-violet-600 flex items-center justify-center shrink-0">
                <Bot className="w-3.5 h-3.5 text-white" />
              </div>
              <div className="flex items-center gap-1 px-3 py-2">
                <span className="w-1.5 h-1.5 rounded-full bg-violet-400 pulse-dot" style={{ animationDelay: "0ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-violet-400 pulse-dot" style={{ animationDelay: "200ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-violet-400 pulse-dot" style={{ animationDelay: "400ms" }} />
              </div>
            </div>
          )}
        </div>

        {/* Session meta */}
        {sessionMeta && (
          <div className="px-6 py-2 border-t border-gray-800 flex items-center gap-4 text-xs text-gray-600">
            <Clock className="w-3 h-3" />
            <span>{fmtMs(sessionMeta.latency)}</span>
            <span>· {sessionMeta.tools} tool calls</span>
            <span>· {sessionMeta.rag} RAG retrievals</span>
            {sessionMeta.traceId && (
              <a href={`/traces/${sessionMeta.traceId}`} className="ml-auto text-violet-500 hover:text-violet-400">
                View trace →
              </a>
            )}
          </div>
        )}

        {/* Input */}
        <div className="px-6 py-4 border-t border-gray-800">
          <form onSubmit={handleSubmit} className="flex gap-3 items-end">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit(e as unknown as React.FormEvent);
                }
              }}
              placeholder="Ask the agent to analyze campaigns, fix pacing, optimize bids..."
              rows={1}
              className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-violet-500 resize-none"
              style={{ minHeight: 44, maxHeight: 120 }}
              disabled={isRunning}
            />
            <button
              type="submit"
              disabled={isRunning || !input.trim()}
              className="px-4 py-3 bg-violet-600 hover:bg-violet-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-xl transition-colors"
            >
              {isRunning ? <Loader2 className="w-4 h-4 text-white animate-spin" /> : <Send className="w-4 h-4 text-white" />}
            </button>
          </form>
        </div>
      </div>

      {/* Right: Sidebar controls */}
      <div className="w-64 shrink-0 flex flex-col bg-[#0f1623] border-l border-gray-800">
        <div className="px-4 py-4 border-b border-gray-800">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Agent Settings</h3>

          <button
            onClick={() => setIsDryRun(!isDryRun)}
            className="flex items-center justify-between w-full p-3 rounded-lg border border-gray-700 hover:border-gray-600 transition-colors"
          >
            <div>
              <p className="text-sm font-medium text-white">Dry Run</p>
              <p className="text-xs text-gray-500 mt-0.5">Preview changes, no execution</p>
            </div>
            {isDryRun
              ? <ToggleRight className="w-6 h-6 text-violet-400 shrink-0" />
              : <ToggleLeft className="w-6 h-6 text-gray-600 shrink-0" />}
          </button>

          {!isDryRun && (
            <div className="mt-2 px-3 py-2 rounded-lg bg-yellow-500/10 border border-yellow-500/20">
              <p className="text-xs text-yellow-400 font-medium">Live mode — actions will execute</p>
              <p className="text-xs text-yellow-600 mt-0.5">Requires ANTHROPIC_API_KEY</p>
            </div>
          )}
        </div>

        <div className="px-4 py-4 border-b border-gray-800">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Available Campaigns</h3>
          <div className="space-y-1.5 max-h-64 overflow-y-auto">
            {campaigns.length === 0 && (
              <p className="text-xs text-gray-600">No campaigns loaded</p>
            )}
            {campaigns.map((c) => (
              <div key={c.id}
                className="px-2 py-1.5 rounded bg-gray-800/50 cursor-pointer hover:bg-gray-800 transition-colors"
                onClick={() => setInput((i) => i ? i + ` (campaign: ${c.id})` : `Analyze campaign ${c.name}`)}
              >
                <p className="text-xs text-gray-300 font-medium truncate">{c.name}</p>
                <p className="text-[10px] text-gray-600">{c.advertiser} · {c.status}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="px-4 py-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Available Tools</h3>
          <div className="space-y-1">
            {[
              { name: "get_campaign_metrics", icon: "📊" },
              { name: "retrieve_policy", icon: "📚" },
              { name: "update_bid_modifier", icon: "⚡" },
              { name: "update_budget", icon: "💰" },
              { name: "pause_campaign", icon: "⏸" },
              { name: "update_targeting", icon: "🎯" },
              { name: "update_supply_sources", icon: "🏗" },
              { name: "route_creative", icon: "🎨" },
            ].map((t) => (
              <div key={t.name} className="flex items-center gap-2 px-2 py-1">
                <span className="text-xs">{t.icon}</span>
                <span className="text-xs text-gray-500 font-mono">{t.name}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

"""Generate AutoBid architecture diagram as PNG using matplotlib."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import matplotlib.font_manager as fm

# ── Palette ────────────────────────────────────────────────────────────────────
BG          = "#0a0d14"
C_BROWSER   = ("#1e3a5f", "#3b82f6")
C_FRONTEND  = ("#1e1b4b", "#7c3aed")
C_API       = ("#1a2e1a", "#22c55e")
C_AGENT     = ("#14532d", "#4ade80")
C_RAG       = ("#1e3a5f", "#60a5fa")
C_TOOLS     = ("#3b1212", "#f87171")
C_DATA      = ("#1c1917", "#a8a29e")
C_TELEMETRY = ("#2d1b69", "#a78bfa")
C_EXTERNAL  = ("#0c1a2e", "#38bdf8")

TEXT_MAIN  = "#f1f5f9"
TEXT_SUB   = "#94a3b8"
TEXT_LABEL = "#cbd5e1"

FIG_W, FIG_H = 24, 15

# ── Helpers ───────────────────────────────────────────────────────────────────
def box(ax, x, y, w, h, fill, border, radius=0.3, alpha=0.93, zorder=2):
    p = FancyBboxPatch((x, y), w, h,
                       boxstyle=f"round,pad=0,rounding_size={radius}",
                       facecolor=fill, edgecolor=border,
                       linewidth=1.8, alpha=alpha, zorder=zorder)
    ax.add_patch(p)

def header(ax, x, y, w, text, fill, border, size=8.5):
    p = FancyBboxPatch((x, y), w, 0.44,
                       boxstyle="round,pad=0,rounding_size=0.18",
                       facecolor=fill, edgecolor=border,
                       linewidth=1.4, alpha=0.95, zorder=3)
    ax.add_patch(p)
    ax.text(x + w/2, y + 0.22, text, fontsize=size, color=TEXT_MAIN,
            fontweight="bold", ha="center", va="center", zorder=4)

def txt(ax, x, y, s, size=6.8, color=TEXT_LABEL, weight="normal",
        ha="center", va="center", zorder=5, mono=True):
    kw = dict(fontsize=size, color=color, fontweight=weight,
              ha=ha, va=va, zorder=zorder)
    if mono:
        kw["fontfamily"] = "monospace"
    ax.text(x, y, s, **kw)

def card(ax, x, y, w, h, fill, border, lines, size=6.5, zorder=4):
    box(ax, x, y, w, h, fill, border, radius=0.16, alpha=0.88, zorder=zorder)
    if isinstance(lines, str):
        lines = [lines]
    step = h / (len(lines) + 1)
    for i, ln in enumerate(lines):
        txt(ax, x + w/2, y + step*(i+1), ln, size=size, zorder=zorder+1)

def arrow(ax, x1, y1, x2, y2, color="#4b5563", lw=1.3, label=None,
          ls=6.0, zorder=3, shrink=5):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color=color,
                                lw=lw, shrinkA=shrink, shrinkB=shrink),
                zorder=zorder)
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        txt(ax, mx, my, label, size=ls, color=color, zorder=zorder+1)

def darrow(ax, x1, y1, x2, y2, color="#4b5563", lw=1.3, zorder=3):
    """Double-headed arrow."""
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="<->", color=color,
                                lw=lw, shrinkA=5, shrinkB=5),
                zorder=zorder)

# ── Canvas ────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
ax.set_xlim(0, FIG_W)
ax.set_ylim(0, FIG_H)
ax.axis("off")

# ── Title ─────────────────────────────────────────────────────────────────────
txt(ax, FIG_W/2, 14.6, "AutoBid  --  AI Campaign Control Agent",
    size=17, color=TEXT_MAIN, weight="bold")
txt(ax, FIG_W/2, 14.22,
    "FastAPI  +  Claude claude-sonnet-4-6  +  ChromaDB RAG  +  Next.js 14  +  SQLite  +  OpenTelemetry-style tracing",
    size=8, color=TEXT_SUB)

# ═══════════════════════════════════════════════════════════════════
# ROW 1  --  Browser  +  Anthropic
# ═══════════════════════════════════════════════════════════════════

# Browser container
box(ax, 0.3, 11.35, 14.4, 2.55, C_BROWSER[0], C_BROWSER[1], radius=0.38)
header(ax, 0.3, 13.46, 14.4, "BROWSER  --  Next.js 14 App Router (TypeScript + Tailwind)",
       C_BROWSER[0], C_BROWSER[1])

pages = [
    ("Dashboard",       "campaigns, alerts\nKPIs, quick actions",    C_BROWSER),
    ("Agent Console",   "SSE stream, tool\ncall inspector, dry-run", C_FRONTEND),
    ("Audit Log",       "approve/reject\nrollback actions",          C_TOOLS),
    ("Experiments",     "A/B lift %\np-value, significance",         C_AGENT),
    ("Campaigns",       "detail view, 24h\nchart, targeting",        C_RAG),
    ("Traces",          "waterfall, span\nlatency breakdown",        C_TELEMETRY),
]
col_w = 14.0 / len(pages)
for i, (title, sub, col) in enumerate(pages):
    px = 0.5 + i * col_w
    box(ax, px, 11.55, col_w - 0.16, 1.72, col[0], col[1], radius=0.2, alpha=0.88, zorder=3)
    txt(ax, px + (col_w-0.16)/2, 12.72, title, size=7.5, color=col[1], weight="bold")
    txt(ax, px + (col_w-0.16)/2, 12.33, sub,   size=6.0, color=TEXT_SUB)

# Anthropic
box(ax, 15.2, 11.35, 8.5, 2.55, C_EXTERNAL[0], C_EXTERNAL[1], radius=0.38)
header(ax, 15.2, 13.46, 8.5, "Anthropic API  (External)", C_EXTERNAL[0], C_EXTERNAL[1])
card(ax, 15.4, 11.55, 8.1, 1.72, "#0a1929", C_EXTERNAL[1],
     ["claude-sonnet-4-6",
      "AsyncAnthropic.messages.stream()",
      "text_delta events  |  tool_use blocks  |  stop_reason"],
     size=7.5)

# ═══════════════════════════════════════════════════════════════════
# ROW 2  --  Backend layer
# ═══════════════════════════════════════════════════════════════════

# Outer backend shell
box(ax, 0.3, 5.6, 23.4, 5.5, "#0d111c", "#374151", radius=0.45, alpha=0.55, zorder=1)
txt(ax, 0.7, 10.88, "BACKEND  --  FastAPI  /  Python 3.11  /  Uvicorn  (async)",
    size=7.5, color="#5b6578", weight="bold", ha="left")

# ── API Routes ────────────────────────────────────────────────────
box(ax, 0.55, 5.8, 4.8, 4.85, C_API[0], C_API[1], radius=0.3, zorder=3)
header(ax, 0.55, 10.21, 4.8, "API Routes  (FastAPI)", C_API[0], C_API[1])
routes = [
    "GET  /campaigns",
    "GET  /campaigns/{id}/metrics",
    "GET  /campaigns/{id}/history",
    "POST /agent/run  (SSE stream)",
    "GET  /agent/sessions",
    "GET/POST  /audit",
    "POST /audit/{id}/approve",
    "POST /audit/{id}/rollback",
    "GET  /experiments",
    "GET  /traces  +  /traces/{id}",
]
for i, r in enumerate(routes):
    txt(ax, 0.75, 10.0 - i*0.44, r, size=6.3, color=TEXT_LABEL, ha="left")

# ── Agent Orchestrator ─────────────────────────────────────────────
box(ax, 5.7, 5.8, 5.4, 4.85, C_AGENT[0], C_AGENT[1], radius=0.3, zorder=3)
header(ax, 5.7, 10.21, 5.4, "Agent Orchestrator", C_AGENT[0], C_AGENT[1])

agent_cards = [
    ("AgentOrchestrator.run()",       ["AsyncGenerator[AgentEvent]", "streams to SSE response"]),
    ("Agentic Loop  (max 10 iter)",   ["stop_reason = end_turn | tool_use", "builds messages[] across turns"]),
    ("Tool Dispatch",                 ["_execute_tool(name, input, span_id)", "routes to 8 tool implementations"]),
    ("Session Accounting",            ["tokens in/out, tool_calls, rag_retrievals", "total_latency_ms, final_answer"]),
    ("agent_tracer",                  ["spans: agent:run, agent:iteration:N"]),
]
cy = 9.95
for title, lines in agent_cards:
    h = 0.22 + len(lines) * 0.28
    box(ax, 5.85, cy - h, 5.1, h, "#0b2018", C_AGENT[1], radius=0.14, alpha=0.85, zorder=4)
    txt(ax, 6.0, cy - 0.15, title, size=6.3, color=C_AGENT[1], weight="bold", ha="left")
    for j, ln in enumerate(lines):
        txt(ax, 6.05, cy - 0.38 - j*0.28, ln, size=5.8, color=TEXT_SUB, ha="left")
    cy -= h + 0.12

# ── RAG Layer ─────────────────────────────────────────────────────
box(ax, 11.45, 5.8, 5.4, 4.85, C_RAG[0], C_RAG[1], radius=0.3, zorder=3)
header(ax, 11.45, 10.21, 5.4, "RAG Layer  --  ChromaDB", C_RAG[0], C_RAG[1])

txt(ax, 11.6, 9.95, "retrieve(query, campaign_id, n_results=5)", size=6.3,
    color=C_RAG[1], weight="bold", ha="left")
txt(ax, 11.6, 9.65, "Embedding: all-MiniLM-L6-v2  |  metric: cosine", size=5.8,
    color=TEXT_SUB, ha="left")

collections = [
    ("policies_playbooks",   ["budget_pacing_policy", "bid_modifier_playbook",
                               "targeting_constraints", "supply_quality_policy",
                               "approval_policy"], C_RAG[1]),
    ("campaign_history",     ["bid change events", "targeting updates",
                               "performance summaries"], "#22d3ee"),
    ("telemetry_aggregates", ["hourly pacing snapshots",
                               "metric summaries"], "#818cf8"),
]
cy = 9.28
for name, items, col in collections:
    h = 0.3 + len(items) * 0.25
    box(ax, 11.6, cy - h, 5.1, h, "#0a1422", col, radius=0.14, alpha=0.88, zorder=4)
    txt(ax, 11.72, cy - 0.16, name, size=6.2, color=col, weight="bold", ha="left")
    for j, itm in enumerate(items):
        txt(ax, 11.78, cy - 0.37 - j*0.25, f"  {itm}", size=5.5,
            color=TEXT_SUB, ha="left")
    cy -= h + 0.12

txt(ax, 11.6, 6.02, "format_context_for_prompt()  --  ranked, deduplicated,", size=5.8,
    color="#6b7280", ha="left")
txt(ax, 11.6, 5.82, "source-attributed grounding block injected into messages[]", size=5.8,
    color="#6b7280", ha="left")

# ── Tool Engine ────────────────────────────────────────────────────
box(ax, 17.2, 5.8, 6.2, 4.85, C_TOOLS[0], C_TOOLS[1], radius=0.3, zorder=3)
header(ax, 17.2, 10.21, 6.2, "Tool Engine  --  Safe Action Interface", C_TOOLS[0], C_TOOLS[1])

tools = [
    ("get_campaign_metrics",  "read-only SELECT",                         "#22c55e"),
    ("retrieve_policy",       "RAG cosine search",                        "#60a5fa"),
    ("update_bid_modifier",   "clamp [0.50x-2.00x]  |  >50% -> approval","#f59e0b"),
    ("update_budget",         ">25% change -> approval gate",             "#f59e0b"),
    ("pause_campaign",        "ALWAYS requires approval",                  "#f87171"),
    ("update_targeting",      "auto-approved",                            "#86efac"),
    ("update_supply_sources", "auto-approved",                            "#86efac"),
    ("route_creative",        "auto-approved",                            "#86efac"),
]
ty = 9.95
for name, note, col in tools:
    box(ax, 17.35, ty - 0.44, 5.9, 0.42, "#1a0808", col,
        radius=0.12, alpha=0.75, zorder=4)
    txt(ax, 17.48, ty - 0.16, name, size=6.5, color=col, weight="bold", ha="left")
    txt(ax, 17.48, ty - 0.34, note, size=5.6, color=TEXT_SUB, ha="left")
    ty -= 0.50

# Safety strip
box(ax, 17.35, 5.88, 5.9, 0.76, "#1a0505", C_TOOLS[1], radius=0.14, alpha=0.85, zorder=4)
txt(ax, 17.5, 6.42, "Safety Layer", size=6.5, color=C_TOOLS[1], weight="bold", ha="left")
txt(ax, 17.5, 6.2,  "idempotency_key = SHA256(campaign+action+params+day)", size=5.8, color=TEXT_SUB, ha="left")
txt(ax, 17.5, 6.02, "dry_run=True -> no DB writes  |  rollback_params snapshot", size=5.8, color=TEXT_SUB, ha="left")

# ═══════════════════════════════════════════════════════════════════
# ROW 3  --  Data Layer  +  Telemetry
# ═══════════════════════════════════════════════════════════════════

# Data layer
box(ax, 0.3, 0.9, 14.4, 4.45, C_DATA[0], C_DATA[1], radius=0.38, zorder=2)
header(ax, 0.3, 4.91, 14.4,
       "Data Layer  --  SQLite  /  aiosqlite  /  SQLAlchemy Async ORM",
       C_DATA[0], C_DATA[1])

tables = [
    ("campaigns", [
        "id, name, advertiser, status",
        "optimization_goal (cpa/roas/ctr/reach)",
        "daily_budget_usd, spend_today_usd",
        "base_bid_cpm, bid_modifier",
        "bid_floor_cpm, bid_ceiling_cpm",
        "pacing_rate, pacing_type",
        "targeting (JSON), supply_sources",
        "creative_ids, blocked_domains",
    ]),
    ("campaign_snapshots", [
        "campaign_id, hour_ts",
        "impressions, clicks, conversions",
        "spend_usd, revenue_usd",
        "avg_bid_cpm",
        "win_rate, fill_rate",
    ]),
    ("audit_logs", [
        "id, idempotency_key",
        "trace_id, span_id",
        "action_type, campaign_id",
        "status: dry_run | pending_approval",
        "         | completed | rolled_back",
        "params_before, params_requested",
        "params_after (null if pending)",
        "agent_rationale (text)",
        "rag_sources (JSON array)",
        "rollback_params, latency_ms",
    ]),
    ("agent_sessions", [
        "id, trace_id",
        "user_query, status",
        "is_dry_run",
        "total_tokens_input/output",
        "tool_calls_count",
        "rag_retrievals_count",
        "total_latency_ms",
        "final_answer (text)",
    ]),
    ("experiments", [
        "id, name, hypothesis",
        "metric (cpa/roas/ctr)",
        "status (running/completed)",
        "control_campaign_ids (JSON)",
        "treatment_campaign_ids (JSON)",
        "control_metric_value",
        "treatment_metric_value",
        "lift_pct, p_value",
        "is_significant (bool)",
    ]),
]

col_w = 14.0 / len(tables)
for i, (tname, cols) in enumerate(tables):
    tx = 0.48 + i * col_w
    tw = col_w - 0.14
    th = len(cols) * 0.31 + 0.5
    ty = 0.96
    box(ax, tx, ty, tw, th, "#100e0c", C_DATA[1], radius=0.18, alpha=0.9, zorder=3)
    txt(ax, tx + tw/2, ty + th - 0.22, tname, size=7.0, color=C_DATA[1],
        weight="bold")
    txt(ax, tx + tw/2, ty + th - 0.40,
        "_" * (len(tname)+2), size=5, color=C_DATA[1])
    for j, col in enumerate(cols):
        txt(ax, tx + 0.08, ty + th - 0.58 - j*0.31, col, size=5.3,
            color=TEXT_SUB, ha="left")

# Telemetry
box(ax, 15.2, 0.9, 8.5, 4.45, C_TELEMETRY[0], C_TELEMETRY[1], radius=0.38, zorder=2)
header(ax, 15.2, 4.91, 8.5,
       "Telemetry  --  In-Process Distributed Tracing",
       C_TELEMETRY[0], C_TELEMETRY[1])

tracers = [
    ("agent_tracer",   ["agent:run", "agent:iteration:N"],           C_AGENT[1]),
    ("rag_tracer",     ["rag:retrieve"],                             C_RAG[1]),
    ("tool_tracer",    ["tool:{name}"],                              C_TOOLS[1]),
]
tw = (8.1) / len(tracers) - 0.15
for i, (name, spans, col) in enumerate(tracers):
    tx2 = 15.35 + i * (8.1 / len(tracers))
    box(ax, tx2, 3.4, tw, 1.3, "#120e2a", col, radius=0.18, alpha=0.88, zorder=3)
    txt(ax, tx2 + tw/2, 4.48, name, size=6.5, color=col, weight="bold")
    for j, sp in enumerate(spans):
        txt(ax, tx2 + tw/2, 4.1 - j*0.32, sp, size=6.0, color=TEXT_SUB)

card(ax, 15.35, 2.6, 8.1, 0.65, "#160e2d", C_TELEMETRY[1],
     ["Span { span_id, parent_span_id, name, service, start_ms, end_ms, status, attributes, events }"],
     size=6.3, zorder=3)

card(ax, 15.35, 1.55, 8.1, 0.92, "#0f0b22", "#6d28d9",
     ["_trace_store: dict[trace_id -> list[Span]]  (in-process, no external dep)",
      "Exposed: GET /traces  |  GET /traces/{trace_id}  ->  waterfall UI",
      "Production: replace with OTLP exporter -> Jaeger / Grafana Tempo"],
     size=6.2, zorder=3)

txt(ax, 15.35, 1.22,
    "Span.service in {autobid-agent, autobid-rag, autobid-tools}  --  color-coded in UI waterfall",
    size=5.8, color="#4b5563", ha="left")

# ═══════════════════════════════════════════════════════════════════
# ARROWS
# ═══════════════════════════════════════════════════════════════════

# Browser -> API (RSC + SSE)
arrow(ax, 7.5, 11.35, 3.1, 10.65, color=C_FRONTEND[1], lw=1.6,
      label="RSC fetch()  +  SSE stream  (text/event-stream)", ls=6.2)

# API -> Agent
arrow(ax, 5.35, 9.0, 5.7, 9.0, color=C_API[1], lw=1.5,
      label="dispatch run()", ls=6.0)

# Agent <-> Anthropic
ax.annotate("", xy=(15.2, 12.62), xytext=(11.1, 12.62),
            arrowprops=dict(arrowstyle="<->", color=C_EXTERNAL[1],
                            lw=1.8, shrinkA=5, shrinkB=5), zorder=4)
txt(ax, 13.15, 12.82,
    "AsyncAnthropic.messages.stream()  |  tool_use blocks  <->  tool_results",
    size=6.2, color=C_EXTERNAL[1])

# Agent -> RAG
arrow(ax, 11.1, 8.5, 11.45, 8.5, color=C_RAG[1], lw=1.5,
      label="retrieve_policy tool call", ls=6.0)
arrow(ax, 11.45, 8.1, 11.1, 8.1, color=C_RAG[1], lw=1.3,
      label="grounding context", ls=6.0)

# Agent -> Tools
arrow(ax, 11.1, 7.2, 17.2, 8.2, color=C_TOOLS[1], lw=1.5,
      label="tool dispatch (update_bid, update_budget, pause...)", ls=6.2)

# Tools -> Data
arrow(ax, 20.3, 5.8, 10.5, 5.22, color=C_DATA[1], lw=1.4,
      label="INSERT audit_log  |  UPDATE campaign", ls=6.0)

# API -> Data (reads)
arrow(ax, 2.95, 5.8, 4.5, 5.35, color=C_DATA[1], lw=1.2,
      label="SELECT", ls=5.8)

# Agent/RAG/Tools -> Telemetry
arrow(ax, 8.4, 5.8, 17.0, 4.9, color=C_TELEMETRY[1], lw=1.1,
      label="start/end span", ls=5.8)
arrow(ax, 14.15, 5.8, 17.5, 4.9, color=C_TELEMETRY[1], lw=1.0)
arrow(ax, 19.6, 5.8, 19.6, 5.35, color=C_TELEMETRY[1], lw=1.0)

# Telemetry -> Traces API
arrow(ax, 15.2, 3.1, 5.35, 5.3, color=C_TELEMETRY[1], lw=1.1,
      label="GET /traces", ls=5.8)

# ═══════════════════════════════════════════════════════════════════
# CONTROL PLANE ANNOTATION
# ═══════════════════════════════════════════════════════════════════
ax.text(0.5, 0.52,
        "Control-Plane Boundary:  AutoBid sets campaign knobs (bid_modifier, budget, targeting, supply_sources)."
        "  Per-request bidding engine reads these knobs deterministically at auction time -- no LLM on the hot path.",
        fontsize=6.8, color="#6b7280", ha="left", va="center",
        fontfamily="monospace",
        bbox=dict(fc="#0d111c", ec="#374151", pad=4,
                  boxstyle="round,pad=0.3"))

# ═══════════════════════════════════════════════════════════════════
# LEGEND
# ═══════════════════════════════════════════════════════════════════
items = [
    (C_BROWSER[1],   "Browser/Frontend"),
    (C_AGENT[1],     "Agent Orch."),
    (C_RAG[1],       "RAG Layer"),
    (C_TOOLS[1],     "Tool Engine"),
    (C_DATA[1],      "Data Layer"),
    (C_TELEMETRY[1], "Telemetry"),
    (C_EXTERNAL[1],  "Anthropic API"),
]
lx = FIG_W - 0.4
txt(ax, lx - 14.5, 0.52, "Layer key:", size=6.2, color=TEXT_SUB,
    weight="bold", ha="left")
for i, (col, label) in enumerate(items):
    ix = lx - 13.5 + i * 2.0
    p = FancyBboxPatch((ix, 0.34), 0.28, 0.22,
                       boxstyle="round,pad=0,rounding_size=0.04",
                       facecolor=col, edgecolor=col, alpha=0.85, zorder=5)
    ax.add_patch(p)
    txt(ax, ix + 0.36, 0.45, label, size=5.5, color=col, ha="left")

# ── Save ──────────────────────────────────────────────────────────
out = "/Users/syefai/workspace/AutoBid/docs/architecture.png"
fig.savefig(out, dpi=180, bbox_inches="tight",
            facecolor=BG, edgecolor="none")
plt.close(fig)
print(f"Saved -> {out}")

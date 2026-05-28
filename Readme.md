# AutoBid — Multi-Agentic Campaign Control Plane

## What It Is

AutoBid is a production-architecture agentic system that sits above the real-time bidding path and continuously optimizes a fleet of programmatic ad campaigns. It implements a closed-loop **Observe → Reason → Act → Evaluate** cycle: a LangGraph multi-agent pipeline fetches live metrics and retrieves grounding context from policy/playbook documents, proposes typed campaign control actions, enforces a multi-layer safety stack before anything executes, and logs every decision in a queryable audit trail with rollback support.

The system is explicitly designed as an **AI control plane** — it influences production campaign outcomes without touching the per-request serving path. It mirrors the architectural boundary described in production AdTech systems between the real-time bidder (microsecond decisions) and the slower control loop that adjusts the parameters those bidders operate under.

---

## Agentic Workflow Architecture

The pipeline is built on **LangGraph** with a Pydantic `BaseModel` state object that flows through seven specialized nodes:

```
START → Planner → Analyst → Optimizer → Auditor → Gatekeeper → Executor → Reviewer → [loop | END]
```

Each node has a single responsibility:

| Node | Role in ACE loop | Implementation |
|---|---|---|
| **Planner** | Decompose goal into typed `PlanStep` objects with priorities | Claude structured-output tool call |
| **Analyst** | **Observe** — fetch live metrics + retrieve RAG context | SQL metrics query + hybrid RAG retrieval |
| **Optimizer** | **Reason** — propose specific parameter changes grounded in context | Claude with forced `propose_actions` tool; cites RAG sources |
| **Auditor** | Independent policy compliance review | Adversarial Claude call with `audit_actions` tool; per-action severity + `requires_human_approval` flag |
| **Gatekeeper** | Structural enforcement (dry-run, hard limits, stale-campaign checks) | LLM-free; purely deterministic rule checks |
| **Executor** | **Act** — dispatch approved actions; pause for human sign-off | Pydantic param validation → typed tool dispatch; `interrupt()` for approval gate |
| **Reviewer** | **Evaluate** — summarize outcomes, decide whether to iterate | Claude call; sets `optimization_complete` or loops back to Analyst |

The graph supports multi-iteration runs: the Reviewer can route back to the Analyst for a second pass if the first set of changes didn't fully satisfy the goal. Maximum iterations are configurable and enforced.

**Human-in-the-loop** is a first-class feature. When the user enables the "Require Approval" flag, `interrupt_before=["executor"]` pauses the graph before execution. The full action set (both auditor-flagged and auto-approved actions) is surfaced to the operator; approved IDs are forwarded via `Command(resume=...)` and the executor applies decisions before touching any live state.

---

## Campaign Control Action Surface

AutoBid controls six typed action types, matching the full AdTech campaign optimization surface:

| Action | Parameters | Use case |
|---|---|---|
| `update_bid_modifier` | `new_bid_modifier: float [0.5–2.0]` | Pacing correction, CPA optimization |
| `update_budget` | `new_daily_budget_usd: float` | Delivery scaling |
| `pause_campaign` | — | Emergency stop; always requires approval |
| `update_targeting` | `age_min/max`, `geo_includes/excludes`, `device_types`, `interest_segments` | Audience refinement |
| `update_supply_sources` | `add_sources`, `remove_sources` | Inventory quality / win-rate optimization |
| `route_creative` | `creative_weights: dict[creative_id, float]` | Creative performance optimization |

Each action type has a corresponding Pydantic schema (`UpdateBidModifierParams`, etc.) that the executor validates before dispatch. Bad params are caught at the boundary — never inside tool functions.

---

## Hybrid RAG Implementation

Policy and playbook grounding uses a three-collection **ChromaDB** store with a custom **hybrid retrieval** layer:

**Collections:**
- `policies_playbooks` — bid policy rules, budget approval thresholds, pacing playbooks; 44 chunks at startup
- `campaign_history` — prose summaries of past optimization actions per campaign
- `telemetry_aggregates` — narrative metric summaries for trend grounding

**Retrieval strategy:**

For `policies_playbooks`, dense cosine similarity (ChromaDB + sentence-transformers) is fused with **BM25Okapi** keyword search using **Reciprocal Rank Fusion (RRF, k=60)**. Policy documents contain exact terminology ("bid_modifier ceiling", "pacing_ratio threshold") that keyword search reliably catches where semantic similarity sometimes drifts. Other collections use dense-only retrieval since they contain more narrative text.

```python
# RRF score = Σ 1 / (k + rank_i) across dense and keyword ranked lists
def _reciprocal_rank_fusion(dense, keyword, k=60) -> list[dict]:
    ...
```

**Optimizations:**
- Results are cached in-process (LRU, 256 entries) keyed by `(query, collections, n_results, campaign_id)`. The same policy context requested by both the Analyst and Optimizer for the same goal is a single ChromaDB round-trip.
- Historical performance data (time-series, exact values) is **not** retrieved through RAG — agents use a typed `query_telemetry_aggregates` SQL tool instead. RAG is reserved for unstructured policy context; structured data stays in the query path.
- The `retrieve()` function is decorated with `@traceable(run_type="retriever")` so every RAG call appears as a child span in LangSmith with query text, result count, and latency.

---

## Tool Safety Architecture

Every campaign control tool is wrapped by a `@tool_guard` decorator that enforces three pre-execution checks in sequence:

**1. Sliding-window rate limiter**
Per-session counter with a 60-second window. Dry-run calls bypass the limiter. On breach, returns `status="rate_limited"` without touching the database.

**2. Idempotency check**
SHA-256 key over `(campaign_id, action_type, params)`. Before executing, the guard queries the audit log for a completed or dry-run entry with a matching key. If found, returns the existing result without re-executing. Prevents duplicate writes on retries or parallel runs.

**3. Hard per-step change limits**
Absolute ceilings enforced regardless of human approval:
- `update_bid_modifier`: max 20% change per step (configurable)
- `update_budget`: max 50% change per step (configurable)

These are applied in the **Gatekeeper** node (before execution) and again inside the `@tool_guard` (at execution time) as a defense-in-depth measure.

**Dual approval layers:**
- **Auditor** (LLM): flags policy-level gates (`requires_human_approval=True`) — bid changes >50%, budget changes >25%, any `pause_campaign`
- **Gatekeeper** (deterministic): blocks dry-run mode, hard limit violations, stale campaign references

**Rollback:**
Every tool records a pre-action snapshot before writing. A `rollback` action type in the audit log restores the prior state. In production, snapshots are backed by Redis; in development the in-process store is used automatically.

---

## AgentOps: Evaluation, Judging, and Experimentation

### Golden eval harness

A `EvalHarness` runs the optimizer → auditor → gatekeeper pipeline against **15 golden test cases** covering three categories:

- **6 anomaly cases**: underpacing (severe/moderate), overpacing, high CPA, ROAS opportunity, low win rate, creative variance
- **5 policy rule cases**: large budget increase (triggers approval), large bid increase (triggers approval), pause (always approval), low-confidence block, contradictory actions on same campaign
- **4 tool selection cases**: reduce CPA, maximize reach, fix underpacing fast, creative optimization

Each `GoldenCase` specifies `expected_action_types`, `forbidden_action_types`, `should_trigger_approval`, and `should_be_blocked_by_audit`, plus KPI targets.

**Scoring is two-layer:**
1. **Deterministic**: F1 score over predicted vs. expected action types; schema feasibility rate (fraction of proposed actions that pass Pydantic validation); policy compliance binary check
2. **LLM-as-a-Judge**: A separate Claude call with a forced `score_proposal` tool scores four dimensions independently — `plan_quality`, `kpi_alignment`, `feasibility`, `policy_compliance` — on a 0.0–1.0 scale with a reasoning field

Composite score: `0.35 × F1 + 0.25 × feasibility + 0.25 × kpi_alignment + 0.15 × plan_quality`

### A/B experimentation (LangSmith)

An `run_ab_experiment()` runner executes both groups concurrently:
- **Group A (control)**: deterministic baseline optimizer using hardcoded heuristics (pacing ratios → bid ±10%, CPA ratio → bid reduction, win rate threshold → supply pruning)
- **Group B (treatment)**: full LangGraph agent with RAG-grounded proposals

Both groups are scored by the LLM judge. Results are logged to LangSmith under separate projects (`AutoBid/<exp_id>-baseline` and `AutoBid/<exp_id>-agent`) for side-by-side comparison. Statistical significance (p-value, lift %) is computed and surfaced in the Experiments UI.

The baseline also serves as the **deterministic fallback**: when a circuit breaker trips or a timeout occurs, the optimizer node falls back to `baseline_recommend_all()` rather than failing the workflow.

---

## Observability and Reliability

### End-to-end tracing

LangSmith tracing is activated at startup (`setup_langsmith_tracing()` sets `LANGCHAIN_TRACING_V2=true`). This gives full LLM message history, token counts, and tool call arguments for every node.

Beyond LangGraph's automatic node tracing, every RAG call is explicitly decorated with `@traceable(run_type="retriever", name="rag_retrieve")` so retrieval latency and result counts appear as child spans under the parent node trace — not as a black box.

A custom **distributed trace store** (SQLite-backed) records per-workflow trace waterfalls with service-colored spans: `autobid-agent` (purple), `autobid-rag` (cyan), `autobid-tools` (green). These are queryable via the `/traces` API and rendered in the portal as a Gantt-style waterfall.

### Circuit breakers and timeouts

Every LLM node call is wrapped by `call_with_guard()`:

```python
async def call_with_guard(coro, circuit, timeout_s=30, node_name=""):
    if circuit.is_open():
        raise CircuitOpenError(f"{node_name} circuit is open")
    try:
        result = await asyncio.wait_for(coro, timeout=timeout_s)
        circuit.record_success()
        return result
    except (asyncio.TimeoutError, Exception) as exc:
        circuit.record_failure()
        raise NodeTimeoutError(...) from exc
```

The `CircuitBreaker` class implements the standard CLOSED/OPEN/HALF_OPEN state machine with configurable failure threshold (default: 3 consecutive failures) and recovery window (default: 60 seconds). Separate breakers are maintained for each node (`optimizer_breaker`, `auditor_breaker`, etc.).

**Fallbacks on circuit open:**
- Optimizer → `build_fallback_optimizer_output()`: calls `baseline_recommend_all()`, marks actions with `[FALLBACK]` prefix, emits `optimizer_fallback` stream event to the UI
- Auditor → `build_fallback_auditor_output()`: auto-approves all actions with `severity=info`, emits `auditor_fallback` event

This ensures the workflow always produces an outcome — safe defaults rather than hard failures.

---

## Architecture Summary

```
┌─────────────────────────────── Control Plane (AutoBid) ────────────────────────────────┐
│                                                                                         │
│   User goal (NL)                                                                        │
│       │                                                                                 │
│       ▼                                                                                 │
│   Planner → Analyst ──────────────────── Hybrid RAG ─────────────────────────────────  │
│                │                         (BM25 + dense, RRF)                           │
│                │   live metrics (SQL)     policies / campaign history / telemetry       │
│                ▼                                                                        │
│           Optimizer (Claude) ──► proposed ProposedAction[]                             │
│                │                                                                        │
│           Auditor  (Claude) ──► approved / blocked / pending_approval                  │
│                │                                                                        │
│           Gatekeeper (rules) ──► dry-run / hard-limit / stale-campaign gates           │
│                │                                                                        │
│           [Human approval gate] ◄─── interrupt() / resume via UI                      │
│                │                                                                        │
│           Executor ──► @tool_guard ──► rate limit / idempotency / hard Δ              │
│                │         │                                                              │
│                │         └──► Audit log (before/after/rationale/RAG sources)           │
│                │              Redis snapshot (rollback support)                         │
│                ▼                                                                        │
│           Reviewer ──► iterate or complete                                              │
│                                                                                         │
│   Observability: LangSmith traces + custom span store                                  │
│   Reliability:   circuit breakers + timeouts + deterministic fallback                  │
│   Evals:         15-case golden suite + LLM judge + A/B (agent vs. baseline)           │
│                                                                                         │
└─────────────────────────── Campaign database / bidding parameters ─────────────────────┘
                                          ▲
                               (real-time serving path — untouched by agents)
```

**Tech stack:** Python 3.11, FastAPI (SSE streaming), LangGraph, LangChain Anthropic, ChromaDB, SQLAlchemy async (SQLite/Postgres-ready), LangSmith, Next.js 16 (React, Tailwind).

---

## Mapping to the Role

| Job requirement | AutoBid implementation |
|---|---|
| Bidder-adjacent agents for campaign control actions | 7-node LangGraph pipeline controlling bid modifiers, budgets, targeting, supply sources, creative routing |
| Production-grade RAG: policies, history, telemetry | 3-collection ChromaDB store; hybrid BM25 + dense retrieval; RRF fusion; LRU cache; LangSmith-traced |
| Safe tool interfaces: idempotency, audit, dry-run, approval gates, rollback | `@tool_guard` (rate limit + idempotency + hard limits); dual-layer approval (LLM auditor + deterministic gatekeeper); Redis snapshot rollback |
| Eval harnesses, regression suites, A/B experiments, outcome metrics | 15 golden cases; LLM-as-a-Judge (4 KPI dimensions); LangSmith A/B runner; CPA/ROAS/pacing metrics |
| End-to-end observability (prompts, retrieval, tools, latency) | LangSmith full-trace; `@traceable` on RAG; custom distributed span store; Gantt waterfall UI |
| Circuit breakers, timeouts, safe defaults | Per-node circuit breakers (CLOSED/OPEN/HALF_OPEN); `asyncio.wait_for`; deterministic baseline fallback |
| AI control plane — influence production without destabilizing serving | Control plane architecture explicitly separated from per-request bidding; all writes via gated, audited, rollback-able tool layer |
| Programmatic advertising domain knowledge | Native AdTech vocabulary: pacing ratios, CPA/ROAS targeting, bid modifiers, supply source selection, creative routing, win rate |

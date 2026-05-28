# AutoBid Changelog

## [Unreleased]

### Added — LangSmith End-to-End Tracing & Reliability Patterns

---

**LangSmith end-to-end tracing (`agent/langsmith_tracing.py`, new)**

`setup_langsmith_tracing()` is called once in the FastAPI lifespan. It sets the three standard LangChain env vars (`LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`) from config so that every subsequent LangGraph and LangChain call automatically ships a trace to LangSmith — no per-node code changes required for those layers.

Trace hierarchy visible in the LangSmith UI:

```
workflow_run  (LangGraph graph run)
  └─ planner_node
  └─ analyst_node
       └─ rag_retrieve  ← @traceable: query, collections, result count, latency
  └─ optimizer_node
       └─ ChatAnthropic ← auto-traced: messages, tool calls, token counts
  └─ auditor_node
       └─ ChatAnthropic
  └─ gatekeeper_node
  └─ executor_node
  └─ reviewer_node
       └─ ChatAnthropic
```

**`@traceable` on `rag/retriever.retrieve()` (new)** — the one gap not covered by LangChain auto-tracing. The `retrieve()` function is a plain Python call (not a LangChain component), so applying `@traceable(run_type="retriever")` explicitly captures: RAG query text, collections queried, n_results requested, the returned document list, and end-to-end latency (including LRU cache hits). This makes query rewriting → retrieval context → LLM prompt a single traceable chain in LangSmith.

Set `LANGSMITH_API_KEY` in `.env` to activate. No-ops gracefully if unset.

---

**Reliability patterns (`agent/reliability.py`, new)**

Three-layer guard stack applied to every LLM node:

**1. Timeout** — `call_with_guard()` wraps every LLM coroutine with `asyncio.wait_for(coro, timeout=settings.llm_timeout_seconds)` (default 30 s). A hung Claude call no longer blocks a workflow indefinitely. Raises `NodeTimeoutError` on breach, which triggers the fallback immediately.

**2. Circuit breaker** — one `CircuitBreaker` instance per LLM node type (`optimizer_breaker`, `auditor_breaker`, `planner_breaker`, `reviewer_breaker`), shared across all requests:

| State | Behavior |
|---|---|
| CLOSED | Normal operation; failures increment counter |
| OPEN | All calls rejected instantly (no LLM call made) |
| HALF_OPEN | One probe request allowed after `recovery_seconds`; success → CLOSED, failure → OPEN |

Opens after `circuit_breaker_failure_threshold` consecutive failures (default 3). Recovers after `circuit_breaker_recovery_seconds` (default 60 s). `get_all_breaker_status()` exposes the live state of all four breakers.

**3. Deterministic fallback** — when the optimizer circuit opens or times out, `build_fallback_optimizer_output()` calls `evals/baseline.py`'s `baseline_recommend_all()` to produce rule-based actions (pacing, CPA, ROAS heuristics). The rest of the graph (auditor → gatekeeper → executor) continues normally — the fallback is invisible to downstream nodes. Fallback actions are tagged with `[FALLBACK]` prefix in rationale and emit an `optimizer_fallback` stream event.

When the auditor circuit opens, `build_fallback_auditor_output()` auto-approves all proposed actions with `severity=info`. The gatekeeper still enforces hard limits, so no out-of-bounds action can execute even via the fallback path.

**Emits two new stream event types** visible in `WorkflowConsole.tsx`:
- `optimizer_fallback` — amber, shows reason + fallback action count
- `auditor_fallback` — amber, shows reason

**Files modified**
- `backend/config.py` — `llm_timeout_seconds` (30 s), `circuit_breaker_failure_threshold` (3), `circuit_breaker_recovery_seconds` (60 s), `langchain_project` ("AutoBid")
- `backend/main.py` — `setup_langsmith_tracing()` called in lifespan
- `backend/rag/retriever.py` — `@traceable` on `retrieve()`
- `backend/agent/nodes/optimizer.py` — `call_with_guard` + fallback around `llm.ainvoke`
- `backend/agent/nodes/auditor.py` — `call_with_guard` + fallback around `llm.ainvoke`
- `frontend/lib/types.ts` — `optimizer_fallback`, `auditor_fallback` added to `WorkflowEvent` union
- `frontend/components/agent/WorkflowConsole.tsx` — `EventRow` renders both fallback event types

---

### Changed — Evaluation Backend: Braintrust → LangSmith

Replaced the Braintrust SDK with LangSmith for A/B experiment logging and run tracing.

| | Before | After |
|---|---|---|
| SDK | `braintrust>=0.0.100` | `langsmith>=0.1.0` |
| Config key | `BRAINTRUST_API_KEY` | `LANGSMITH_API_KEY` |
| Runner file | `evals/braintrust_runner.py` | `evals/langsmith_runner.py` |
| Remote logging | Braintrust experiment + `experiment.log()` | LangSmith `client.create_run()` under `AutoBid/<exp_id>-baseline` and `AutoBid/<exp_id>-agent` projects |
| UI comparison | Braintrust experiment view | LangSmith side-by-side project comparison |

`ExperimentResult` field renamed `braintrust_logged → langsmith_logged`; new `langsmith_project` field carries the project name prefix for direct navigation. No behavioral change — the experiment runs and scores identically whether LangSmith is configured or not.

---

### Added — Adaptive RAG, Hybrid Search, Structure-Aware Chunking & Telemetry SQL Endpoints

**Hybrid search (`rag/retriever.py`)** — dense vector retrieval is now combined with BM25 keyword search for the `policies_playbooks` collection and fused via Reciprocal Rank Fusion (RRF, k=60). Policy documents benefit from both: dense handles paraphrase/intent queries ("when should I lower my bid"), BM25 handles exact terminology matches ("bid_modifier_change_pct > 0.50"). Campaign history and telemetry collections remain dense-only (prose summaries rather than keyword-heavy content).

| Collection | Retrieval method |
|---|---|
| `policies_playbooks` | Dense cosine + BM25 → RRF fusion |
| `campaign_history` | Dense cosine |
| `telemetry_aggregates` | Dense cosine |

Result format now includes `method` (`rrf` or `dense`) and `heading_path` fields; `format_context_for_prompt()` surfaces both in the grounding block so the LLM can cite back to specific policy sections.

**In-process retrieval cache (`rag/retriever.py`)** — `_cached_retrieve` is wrapped with `@lru_cache(maxsize=256)` keyed by `(query, collections, n_results, campaign_id)`. Identical queries within a workflow session (e.g., same policy context requested by both analyst and optimizer) skip the ChromaDB embedding round-trip entirely. Cache is invalidated on any `index_*` or `add_*` call.

**Structure-aware markdown chunker (`rag/chunker.py`, new)** — replaces the flat `"\n\n"` paragraph splitter with a heading-aware pipeline:
- H1–H4 section boundaries are never split; each chunk carries a `heading_path` breadcrumb (e.g., `"Bid Modifier Playbook > Safety Rules"`)
- Tables (`|...|` rows) are kept as atomic chunks — never bisected
- Fenced code blocks are kept as atomic chunks
- Prose is paragraph-merged up to `max_chars=900` then sentence-split with `overlap_chars=80` carry-forward

Each `ChunkResult` has `chunk_type` (`paragraph | table | code | heading_section`) and `heading_path` stored in ChromaDB metadata. *Note: for PDF/Word/HTML documents, replace `chunk_markdown()` with a Docling parser that produces the same `ChunkResult` schema — the rest of the pipeline is format-agnostic.*

`index_policy_documents()` now uses the structure-aware chunker and rebuilds the BM25 index atomically after upsert.

**Telemetry aggregate endpoints (`api/telemetry_api.py`, new)** — structured SQL-backed endpoints for agents to query exact performance numbers instead of using RAG over unstructured metric text:

| Endpoint | Description |
|---|---|
| `GET /telemetry/aggregate` | Aggregate one metric (CPA, ROAS, CTR, pacing, spend…) over a time window (1h–30d), optionally scoped to one campaign |
| `GET /telemetry/compare` | Cross-campaign leaderboard for a metric with fleet-average deviation (`pct_vs_fleet`) |
| `GET /telemetry/timeseries/{id}` | Hourly time-series rows for a single campaign |

Supported metrics: `cpa`, `roas`, `ctr`, `pacing_rate`, `spend`, `impressions`, `clicks`, `conversions`, `win_rate`. Computed from `CampaignSnapshot` via SQLAlchemy aggregate queries (not from unstructured text).

**`query_telemetry_aggregates` agent tool (`agent/tools.py`, `agent/schemas.py`)** — pre-built Pydantic-validated tool that agents call to get structured metric data from the SQL layer. Added to `OPTIMIZER_TOOLS` as `query_telemetry` — the optimizer can call it *before* proposing actions to verify CPA/pacing assumptions, producing a `telemetry_queries` count in the `actions_proposed` stream event. This enforces the architectural boundary: structured time-series data → SQL tool, unstructured knowledge → RAG.

---

### Added — Evaluation Harness, LLM-as-a-Judge & A/B Experimentation

Replaces vibe-based testing with a continuous evaluation framework. Three layers:
golden dataset → deterministic scoring → LLM judge → optional Braintrust remote logging.

---

**Golden dataset (`evals/dataset.py`, new)** — 15 hand-crafted test cases across three categories:

| Category | Cases | What it tests |
|---|---|---|
| `anomaly` | 6 | Signal detection: under/over-pacing, CPA blowout, ROAS opportunity, low win rate, creative variance |
| `policy_rule` | 5 | Guardrail correctness: budget gate, bid gate, pause gate, low-confidence handling, contradictory actions |
| `tool_selection` | 4 | Goal → action-type mapping: CPA reduction, reach expansion, urgent pacing fix, creative optimization |

Each `GoldenCase` carries synthetic campaign metrics (matching the exact shape `optimizer._format_metrics()` expects), compact policy context, expected action types, forbidden action types, and per-case pass/fail thresholds for `tool_selection_f1`, `kpi_alignment`, and `feasibility`.

---

**Evaluation harness (`evals/harness.py`, new)** — runs the full optimizer → auditor → gatekeeper pipeline against each golden case without a live database:

- `_MockAsyncDB` satisfies SQLAlchemy queries if the optimizer calls `query_telemetry` (metrics are pre-populated in state so it typically doesn't)
- **Deterministic scores** (no LLM): tool selection F1 (precision × recall on action type sets), schema feasibility (fraction of proposed params that pass Pydantic validation), policy compliance (approval/block expectations matched)
- **LLM judge scores**: plan quality and KPI alignment via an independent `judge_proposal()` call
- Cases run concurrently via `asyncio.gather`; pass threshold checked per dimension per case
- `EvalHarness.run_suite()` aggregates into `EvalSuiteResult` with per-dimension averages and overall pass rate

---

**LLM-as-a-Judge (`evals/judge.py`, new)** — independent Claude call that scores optimizer output on four dimensions using a forced `score_proposal` tool:

| Dimension | What it measures |
|---|---|
| `plan_quality` | Does the action set coherently address the stated goal? |
| `kpi_alignment` | Are proposed param changes directionally correct and well-sized vs targets? |
| `feasibility` | Are params within valid ranges and conservatively sized? |
| `policy_compliance` | Do the proposals respect approval gates, bid floor/ceiling, and hard limits? |

The judge uses a separate Claude instance that never sees the optimizer's context — same API key, independent session. A `_FALLBACK` result of all-zeros is returned if the judge call fails, so harness runs are never blocked by judge errors. `reasoning` field provides a 2–4 sentence explanation, making score breakdowns actionable for debugging.

---

**Rule-based baseline (`evals/baseline.py`, new)** — deterministic Group A for A/B comparison:

- Pacing-based bid adjustment: `pacing < 0.75` → +10%, `pacing > 1.20` → -10%
- CPA-based bid adjustment: `cpa / target_cpa > 1.20` → proportional reduction, capped at -15%
- ROAS-based budget scaling: `roas / target_roas > 1.25` with headroom → +15% budget
- Win-rate supply pruning: `win_rate < 5%` → remove last supply source
- No LLM, no external calls — deterministic and sub-millisecond

---

**LangSmith A/B runner (`evals/langsmith_runner.py`, new)** — compares agent (Group B) vs baseline (Group A) on anomaly golden cases:

- Both groups run concurrently; scoring also concurrent via `asyncio.gather`
- Three scorers: `tool_selection_f1`, `schema_feasibility`, `kpi_alignment`
- Composite score: `0.35 × F1 + 0.25 × feasibility + 0.25 × kpi_alignment + 0.15 × plan_quality`
- `_log_to_langsmith()` logs each result as a LangSmith `create_run` call under projects `AutoBid/<exp_id>-baseline` and `AutoBid/<exp_id>-agent` — the two projects appear side-by-side in the LangSmith UI for direct comparison. Gracefully no-ops if `LANGSMITH_API_KEY` is not configured.
- `ExperimentResult` includes `delta_composite` (B − A) and `langsmith_project` URL prefix for direct navigation

---

**Eval API (`api/eval_api.py`, new)**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/evals/cases` | List golden case metadata (filterable by category) |
| `POST` | `/evals/run` | Run full suite or subset (`case_ids`, `category`) |
| `POST` | `/evals/run/{case_id}` | Run single case, return `EvalResult` |
| `POST` | `/evals/experiment/ab` | Run A/B experiment, log to Braintrust |
| `GET` | `/evals/results/latest` | Return most recent suite result (in-memory) |
| `GET` | `/evals/experiment/latest` | Return most recent A/B experiment result |

---

**`config.py`** — added `langsmith_api_key: str = ""` (read from `LANGSMITH_API_KEY` env var).

**`pyproject.toml`** — added `langsmith>=0.1.0` dependency.

**Files added**
- `backend/evals/__init__.py`
- `backend/evals/dataset.py`
- `backend/evals/judge.py`
- `backend/evals/harness.py`
- `backend/evals/baseline.py`
- `backend/evals/langsmith_runner.py`
- `backend/api/eval_api.py`

**Files modified**
- `backend/main.py` — added `eval_router`
- `backend/config.py` — `braintrust_api_key` field
- `backend/pyproject.toml` — `braintrust` dependency

---

### Added — Action Guardrails, Execution Safety & Redis Rollbacks

**Gatekeeper Node (`agent/nodes/gatekeeper.py`, new)** — a dedicated, LLM-free node inserted between the Auditor and Executor that provides a structural last line of defense before any campaign mutation reaches the tool layer.

Three checks run sequentially for every approved action:

| Check | What it enforces |
|---|---|
| Dry-run gate | If `state.dry_run = True`, all actions are diverted to `gated_actions` — nothing reaches the executor |
| Stale campaign check | Actions referencing a `campaign_id` not in the current `campaign_metrics` snapshot are rejected (stale proposals from a previous iteration) |
| Hard per-step change limit | Actions whose requested delta exceeds `STEP_HARD_LIMITS` are blocked absolutely — these are system-level blocks, not approval gates |

Hard limits: bid modifier ≤ 20% delta per step, daily budget ≤ 50% delta per step (configurable via `config.py`).

Unlike the Auditor's approval gates (which route to human sign-off and can proceed after approval), gatekeeper blocks are unconditional. Gated actions are surfaced in the Reviewer's summary via `gated_actions` on the state. The gatekeeper emits `action_gated`, `action_passed_gate`, and `gatekeeper_complete` stream events so the frontend can show exactly why each action was stopped.

**`@tool_guard` execution safety decorator (`agent/guards.py`, new)** — applied to all six campaign control tools. Three layers of enforcement, evaluated before the tool body runs:

1. **Sliding-window rate limiter** — per-session, max 30 tool calls per 60-second window. Rejects with `RateLimitError` on breach.
2. **Idempotency guard** — computes SHA-256(campaign_id + action_type + canonical_params), queries `AuditLog` for a matching completed result. Returns the existing result immediately if found — the tool body never runs, the DB is not mutated twice.
3. **Hard step-limit check** — fetches the live campaign row, computes the requested delta, raises `HardLimitError` if it exceeds `STEP_HARD_LIMITS`. This is the second enforcement layer (gatekeeper node is the first), so the limit is checked even if a request arrives at the tool layer directly (e.g., in tests or via direct API call).

**Redis pre-action snapshots + auto-rollback (`agent/redis_store.py`, new)** — applied to `update_bid_modifier` and `update_budget` (the two stateful tools that write numeric values back to the DB):

1. `write_snapshot(audit_id, campaign_state)` stores a JSON snapshot of the campaign's mutable fields in Redis with a 24h TTL before any mutation is written
2. The DB update runs; the new state is re-fetched
3. `validate_campaign_state(post_state)` asserts invariants (bid_modifier in [0.50, 2.00], daily_budget > $1.00)
4. On `PostExecutionValidationError`: `read_snapshot(audit_id)` → restore original values to DB → `delete_snapshot(audit_id)` → return `status=rolled_back, auto_rolled_back=True`

Redis is gracefully optional — `_get_redis()` pings on connect and falls back to an in-process dict if Redis is unavailable. This means the app works in demo/dev mode without a running Redis server; the fallback has the same rollback semantics.

`rollback_action()` (existing manual rollback) remains unchanged and is still available as a user-initiated path.

**`@tool_guard` applied to all six campaign control tools:**
- `update_bid_modifier` — rate limit + idempotency + hard limit + Redis snapshot/rollback
- `update_budget` — rate limit + idempotency + hard limit + Redis snapshot/rollback
- `pause_campaign` — rate limit + idempotency
- `update_targeting` — rate limit + idempotency
- `update_supply_sources` — rate limit + idempotency
- `route_creative` — rate limit + idempotency

**`config.py`** — four new fields: `max_bid_modifier_step_pct` (default 0.20), `max_budget_step_pct` (default 0.50), `redis_url` (default `redis://localhost:6379/0`), `snapshot_ttl_seconds` (default 86400).

**`pyproject.toml`** — added `redis>=5.0.0` dependency.

**Files added**
- `backend/agent/guards.py`
- `backend/agent/redis_store.py`
- `backend/agent/nodes/gatekeeper.py`

**Files modified**
- `backend/agent/graph.py` — gatekeeper node inserted; `route_after_gatekeeper` replaces old `route_after_audit`
- `backend/agent/state.py` — `gated_actions: list[ProposedAction]` field added
- `backend/agent/tools.py` — `@tool_guard` applied to all six tools; Redis snapshot/rollback in `update_bid_modifier` and `update_budget`
- `backend/config.py` — four new safety config fields
- `frontend/lib/types.ts` — `WorkflowEvent` union extended with `action_gated`, `action_passed_gate`, `gatekeeper_complete` discriminants
- `frontend/components/agent/WorkflowConsole.tsx` — `EventRow` handles all three gatekeeper event types (orange shield icon, reasons list inline)

---

### Added — Pydantic State Schema & Structured Tool Invocations

**`agent/schemas.py`** (new) is the single source of truth for what every campaign control action accepts. All LLM tool schemas are generated from these models, so the JSON Schema the model sees is always in sync with the server-side validation.

| Action type | Pydantic model | Key constraints |
|---|---|---|
| `update_bid_modifier` | `BidModifierParams` | `new_bid_modifier` in [0.50, 2.00] |
| `update_budget` | `BudgetParams` | `new_daily_budget_usd` > 0, ≤ $1M |
| `update_targeting` | `TargetingParams` | `device_types` enum; at least one field required |
| `update_supply_sources` | `SupplyParams` | add/remove lists must not overlap; both non-empty |
| `route_creative` | `CreativeRouteParams` | each weight in [0.0, 1.0] |
| `pause_campaign` | `PauseParams` | no extra params — just campaign_id + rationale |

`parse_action_params(action_type, raw_dict)` is the single dispatch point: looks up the model, calls `model_validate`, and raises `pydantic.ValidationError` on any violation. This is called in the Executor before any tool function is reached — bad params never enter the tool layer.

**`agent/state.py`** — all five types converted from `TypedDict` to `pydantic.BaseModel`:
- `PlanStep` — `step_type` and `status` are `Literal` enums
- `ProposedAction` — `action_type` uses the `ActionType = Literal[...]` alias from schemas; `confidence` constrained to [0.0, 1.0]
- `AuditFinding` — `severity` is a `Literal` enum
- `ExecutedResult` — `status` is a `Literal` enum
- `AutoBidState` — Pydantic `BaseModel` with `ConfigDict(arbitrary_types_allowed=True)`; all fields have defaults so nodes can return partial dicts; `Annotated[list, operator.add]` reducers are preserved for LangGraph

**`agent/nodes/optimizer.py`** — replaced the single `propose_actions` catch-all tool with **six per-action-type tools** generated from the Pydantic schemas via `schemas.OPTIMIZER_TOOLS`. The LLM now calls `bid_modifier_action`, `budget_action`, `targeting_action`, etc. as separate tool invocations (one per proposed action), so each call is validated against its specific schema. On parse:
1. Field names for this action type's param model are extracted
2. `params_model.model_validate(filtered_args)` is called — `ValidationError` causes the action to be dropped with an error logged, not silently passed through
3. Validated params are serialized back to dict via `model_dump(exclude_none=True)` before storing in `ProposedAction.params`

**`agent/nodes/executor.py`** — added a mandatory Pydantic validation gate before any `tools.*` call: `parse_action_params(action.action_type, action.params)` runs first. On failure the action returns `status=failed` with a structured error — the tool layer is never reached with unvalidated data.

All other nodes updated: dict-style state access (`state["field"]`, `state.get(...)`) replaced with Pydantic attribute access (`state.field`). Mutable step updates use `step.model_copy(update={...})` instead of `{**step, ...}`.

---

### Added — LangGraph Multi-Agent Workflow

Replaced the single-agent orchestration loop with a stateful, multi-node LangGraph pipeline. Each concern is now an independent node with its own system prompt, tool schema, and failure boundary.

**Graph topology** (`START → planner → analyst → optimizer → auditor → executor → reviewer → END`)

| Node | Role | LLM? |
|------|------|-------|
| Planner | Decomposes the user goal into typed plan steps (analyze / optimize_bid / update_budget / update_targeting / update_supply / review) | Yes — `create_plan` tool |
| Analyst | Fetches campaign metrics from DB + runs RAG retrieval against policies/playbooks/telemetry | No |
| Optimizer | Proposes up to 5 data-driven actions grounded in metrics and RAG context | Yes — `propose_actions` tool |
| Auditor | Independent adversarial review; enforces policy thresholds (bid >50% → approval, budget >25% → approval, pause → always approval) | Yes — `audit_actions` tool |
| Executor | Dispatches approved actions to existing tool functions; uses `interrupt()` to pause graph for human sign-off | No |
| Reviewer | Synthesizes results; decides `optimization_complete` or requests another iteration (max 3) | Yes — `submit_review` tool |

**Conditional routing**
- After Auditor: routes to Executor if any actions are approved or pending, otherwise skips directly to Reviewer
- After Reviewer: loops back to Analyst for the next plan step, or exits when all steps are done / `optimization_complete = true`

**Human-in-the-loop approval gate**
- Graph compiles with `interrupt_before=["executor"]`; execution pauses when `pending_approval_actions` is non-empty
- Frontend surfaces a per-action checkbox panel with Approve All / Approve Selected / Reject All controls
- Graph resumes via `POST /agent/sessions/{id}/resume` with `{ approved_ids, rejected_ids }` using LangGraph `Command(resume=...)`

**Checkpointing**
- `MemorySaver` keyed by `session_id` (`thread_id`) preserves full state across interrupt/resume cycles and iteration loops

**New API endpoints**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/agent/workflow/run` | Start workflow; streams SSE node lifecycle + domain events |
| `POST` | `/agent/sessions/{id}/resume` | Resume after human approval; streams remaining execution |
| `GET` | `/agent/sessions/{id}/state` | Return current LangGraph state snapshot |

**New SSE event types**
`workflow_start`, `node_start`, `node_end`, `plan_created`, `metrics_fetched`, `rag_retrieved`, `actions_proposed`, `action_approved`, `action_blocked`, `action_pending_approval`, `audit_complete`, `action_executed`, `review_complete`, `workflow_interrupted`, `workflow_complete`, `workflow_resumed`

**Frontend — WorkflowConsole**
- Pipeline visualization: animated node bubbles showing idle / active (pulsing) / done states
- Plan step checklist: live status icons (○ pending → → in-progress → ✓ completed)
- Audit findings panel: severity-colored findings displayed after auditor runs
- Approval gate: expandable action cards with per-action checkboxes and batch decision buttons
- Event log: structured per-event rendering with icons, scrolls automatically
- Tab switcher on `/agent` page: "Multi-Agent Workflow" (new) vs "Classic Agent" (original SSE-based single-agent)

**Files added**
- `backend/agent/nodes/__init__.py`
- `backend/agent/nodes/planner.py`
- `backend/agent/nodes/analyst.py`
- `backend/agent/nodes/optimizer.py`
- `backend/agent/nodes/auditor.py`
- `backend/agent/nodes/executor.py`
- `backend/agent/nodes/reviewer.py`
- `backend/agent/graph.py`
- `frontend/components/agent/WorkflowConsole.tsx`
- `frontend/components/agent/AgentTabsClient.tsx`

**Files modified**
- `backend/api/agent_api.py` — added three new workflow endpoints; original `/agent/run` preserved
- `frontend/lib/types.ts` — added `WorkflowEvent`, `PlanStep`, `ProposedAction`, `AuditFinding`, `WorkflowNodeName`
- `frontend/lib/api.ts` — added `streamWorkflow()`, `resumeWorkflow()`; refactored to shared `_readSSE` helper
- `frontend/app/agent/page.tsx` — replaced single-component render with tabbed layout

---

## [0.1.0] — Initial Release

### Added

**Agentic campaign control**
- Single-agent orchestration loop using Anthropic Claude claude-sonnet-4-6 via `anthropic` SDK
- 8 campaign control tools: `get_campaign_metrics`, `update_bid_modifier`, `update_budget`, `pause_campaign`, `update_targeting`, `update_supply_sources`, `route_creative`, `rollback_action`
- Idempotent execution via SHA-256(campaign_id + action_type + params) keys
- Dry-run mode: all tool functions simulate execution without writing to DB
- Tiered approval gates: budget changes >25% or pause actions require human sign-off
- Rollback support: re-applies `params_before` from the audit log

**RAG grounding**
- ChromaDB vector store with `all-MiniLM-L6-v2` embeddings
- Three collections: `policies_playbooks`, `campaign_history`, `telemetry_aggregates`
- Multi-collection retrieval with cosine similarity scoring and source attribution
- Context formatted as grounding block injected into every optimizer call

**Observability**
- In-process distributed tracing: `Span` / `Tracer` with `asynccontextmanager` API
- Four tracers: `agent_tracer`, `rag_tracer`, `api_tracer`, `tool_tracer`
- Waterfall trace visualization at `/traces`
- Full audit log at `/audit` with before/after params, rationale, RAG sources, latency

**A/B experimentation**
- `Experiment` model with control/treatment campaign groups, lift_pct, p_value, significance flag
- Seed experiment: CPA optimization bid adjustment, −11.4% lift, p=0.038

**Data model**
- `Campaign`: bid_modifier, daily_budget_usd, pacing_rate, targeting (JSON), supply_sources (JSON)
- `CampaignSnapshot`: hourly performance (impressions, clicks, conversions, spend, revenue, win_rate)
- `AuditLog`: full action lifecycle with idempotency key, approval status, rollback params
- `AgentSession`: token accounting, tool call count, RAG retrieval count, total latency

**Seed data**
- 6 campaigns across 5 advertisers with varied pacing (0.58–1.18) and optimization goals
- 24 hours of hourly snapshots per campaign

**Frontend (Next.js 14 App Router)**
- `/` — dashboard with pacing status, spend, CPA columns
- `/campaigns` — campaign table with budget utilization and performance metrics
- `/agent` — agent console with SSE streaming, dry-run toggle, tool call inspector
- `/audit` — audit log with approve/reject/rollback actions
- `/experiments` — A/B test results with significance badges
- `/traces` — waterfall trace viewer

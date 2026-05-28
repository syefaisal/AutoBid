# AutoBid — Design Decisions

Every significant architectural and implementation choice, with the reasoning behind it.

---

## Architecture

| Decision | What was chosen | Why |
|---|---|---|
| **Control plane vs. serving path** | Agent pipeline runs entirely outside the real-time bidding path; it only modifies campaign parameters that the bidder reads | Real-time bidding operates at millisecond latency — no LLM call can sit in that path. The control plane runs asynchronously and adjusts the knobs (bid modifier, budget, targeting) that the per-request bidder uses. This keeps the serving path deterministic and stable. |
| **Multi-agent pipeline over single agent** | Seven specialized LangGraph nodes (Planner, Analyst, Optimizer, Auditor, Gatekeeper, Executor, Reviewer) | Each node has a single responsibility and a distinct system prompt. A monolithic agent mixing analysis, optimization, and auditing in one context window produces worse results and makes it impossible to test or replace individual steps independently. Separation also means the Auditor is adversarial to the Optimizer by design. |
| **LangGraph over custom orchestration** | LangGraph `StateGraph` with `MemorySaver` checkpointing | LangGraph gives persistent state across nodes, built-in `interrupt_before` for human-in-the-loop pauses, `Command(resume=...)` for resuming after approval, and automatic LangSmith tracing integration. Building this manually would require reimplementing checkpointing, branching logic, and loop detection. |
| **Pydantic `BaseModel` as graph state** | `AutoBidState(BaseModel)` with field-level validation and `Annotated` reducers for append-only fields | Every node write is validated at assignment time, not just at construction. Append-only fields (`messages`, `stream_events`, `errors`) use `operator.add` as the LangGraph reducer — impossible to accidentally overwrite them. Type errors surface immediately rather than silently corrupting state mid-pipeline. |
| **Closed-loop iteration** | Reviewer node can route back to Analyst for another pass | A single pass may partially address a goal (e.g., fix pacing but not CPA). The Reviewer decides whether the current state satisfies the original goal and re-runs if not. `MAX_AGENT_ITERATIONS` caps the loop to prevent infinite cycles. |

---

## RAG Design

| Decision | What was chosen | Why |
|---|---|---|
| **Hybrid retrieval for policy documents** | BM25Okapi keyword search fused with ChromaDB dense vectors via Reciprocal Rank Fusion (RRF, k=60) | Policy documents contain exact terminology — "bid_modifier ceiling", "pacing_ratio threshold" — that keyword search reliably catches even when semantic similarity drifts. Dense-only retrieval misses exact term matches on short, technical phrases. BM25 + dense covers both exact and intent-based queries. |
| **Dense-only for campaign history and telemetry** | Semantic search only for `campaign_history` and `telemetry_aggregates` | These collections contain narrative prose, not exact terminology. BM25 adds no value and increases latency. |
| **Structured data stays out of RAG** | Time-series metrics and exact values are fetched via SQL (`query_telemetry_aggregates`), not retrieved from a vector store | RAG is for unstructured grounding context. Precise numbers retrieved through semantic similarity may be wrong (nearest chunk, not exact value). SQL guarantees exact metric values. Using RAG for structured data is a common hallucination source. |
| **LRU result cache** | 256-entry in-process cache keyed by `(query, collections, n_results, campaign_id)` | The Analyst and Optimizer both retrieve policy context for the same goal in the same workflow run. Without caching, this is two identical ChromaDB round-trips including embedding computation. The cache eliminates the duplicate. |
| **Three separate collections** | `policies_playbooks`, `campaign_history`, `telemetry_aggregates` | Different document types have different retrieval strategies, different metadata filters, and different relevance characteristics. Mixing them in one collection degrades retrieval quality — a policy chunk and a telemetry summary compete on the same embedding space. |
| **`@traceable` on `retrieve()`** | LangSmith `@traceable(run_type="retriever")` decorator applied directly to the retrieve function | LangGraph auto-traces its own nodes but cannot see inside plain Python functions. Without `@traceable`, every RAG call is a black box in the trace — no query text, no result count, no latency. Explicit decoration makes retrieval a first-class observable span. |

---

## Safety Architecture

| Decision | What was chosen | Why |
|---|---|---|
| **Dual approval layers** | LLM Auditor (policy-based, semantic) + deterministic Gatekeeper (rule-based, structural) | The Auditor catches policy violations that require contextual reasoning (e.g., contradictory actions on the same campaign). The Gatekeeper catches structural problems that should never reach an LLM (dry-run suppression, absolute hard limits, stale campaign references). Neither layer alone is sufficient — LLMs can be manipulated or hallucinate; pure rules miss semantic violations. |
| **Gatekeeper is LLM-free** | `gatekeeper_node` is pure Python with no LLM call | Hard limits must be deterministic. If the Gatekeeper used an LLM, a sufficiently convincing rationale could cause it to waive the limit. Rule-based enforcement is unconditional — 20% bid step limit means 20%, always. |
| **`@tool_guard` decorator** | Wraps every campaign control tool with rate limiting, idempotency check, and hard Δ limits before execution | Defense in depth — the Gatekeeper enforces limits at the graph level, but `@tool_guard` re-checks at the tool call level. If any code path bypasses the Gatekeeper and calls a tool directly, the guard still fires. Idempotency prevents duplicate writes on retries. |
| **Idempotency via SHA-256 key** | `SHA-256(campaign_id + action_type + sorted_params)` checked against the audit log before execution | Agent pipelines may retry on transient failures. Without idempotency, a retry applies the same bid change twice. The hash key makes the check cheap and deterministic regardless of how the tool is called. |
| **Hard limits below approval thresholds** | Approval gate: bid >50%, budget >25%. Hard limits: bid step 20%, budget step 50% | Approval gates are policy-level human checks. Hard limits are system-level safety ceilings that cannot be waived even with human approval. The bid step limit (20%) is deliberately conservative — a human approving a 50% bid change still only gets 20% applied per step, requiring multiple iterations to reach large changes. |
| **Rollback via pre-action snapshots** | Every tool saves parameter state before writing; `rollback` action type restores it | Agent mistakes in production need a recovery path. Rollback is O(1) — restore the snapshot. Redis is the production snapshot store; in-process dict is the development fallback. The audit log preserves the full before/after/rationale history even after rollback. |
| **Dry-run mode** | `dry_run: bool` in state; Gatekeeper suppresses all execution when set | Operators need to preview agent behavior before committing to live campaigns. Dry-run runs the full pipeline including LLM calls, auditing, and gatekeeping — it only skips the final write. The audit log records dry-run actions separately so they are distinguishable. |

---

## Human-in-the-Loop Design

| Decision | What was chosen | Why |
|---|---|---|
| **`interrupt_before=["executor"]`** | Graph compiles with LangGraph's `interrupt_before` on the executor node | Pausing before execution (not during) means the full action set — approved and pending — is available for human review before any write occurs. The graph state is checkpointed at the pause point so the session can be resumed from any client. |
| **Two interrupt mechanisms** | `interrupt_before=["executor"]` (graph level) + `interrupt()` inside executor (node level) | `interrupt_before` fires unconditionally. The executor's `interrupt()` call receives the human decision via `Command(resume=...)` as its return value — this is how the approved/rejected IDs reach the executor. The two mechanisms work in sequence: graph pauses, user decides, resume value flows into `interrupt()`. |
| **All actions shown at approval gate** | `workflow_interrupted` event surfaces both `pending_approval_actions` (auditor-flagged) and `approved_actions` (auto-approved) | When "Require Approval" is enabled, the user expects to review everything before execution — not just the actions that exceeded policy thresholds. Showing only the auditor-flagged subset would silently execute approved actions without human review, defeating the purpose of the toggle. |
| **Session state persisted in `sessionStorage`** | `WorkflowConsole` serializes full state (events, pipeline status, approval gate, plan steps) to `sessionStorage` on every change | LangGraph checkpoints the server-side workflow state in `MemorySaver`. If the user navigates away and returns, the client needs to reconstruct the UI from the last known state — otherwise a pending approval gate is lost and the workflow hangs server-side indefinitely. |

---

## Reliability

| Decision | What was chosen | Why |
|---|---|---|
| **Per-node circuit breakers** | Separate `CircuitBreaker` instances for optimizer, auditor, planner, reviewer | A failure in the optimizer (e.g., bad model response) should not trip the auditor's breaker. Node-level breakers give precise failure isolation. Module-level singletons mean failure counts accumulate across all requests — one bad period opens the circuit fleet-wide, same as a real infrastructure circuit breaker. |
| **CLOSED → OPEN → HALF_OPEN state machine** | Standard three-state circuit breaker with configurable failure threshold and recovery window | HALF_OPEN allows the circuit to self-heal after the recovery window without manual intervention. A single probe request is allowed in HALF_OPEN — success closes the circuit, failure re-opens it. This avoids permanently blocking an LLM node after a transient API issue. |
| **`asyncio.wait_for` timeout on every LLM call** | 30-second default timeout per node, configurable via `LLM_TIMEOUT_SECONDS` | LLM API calls can hang indefinitely under load or network issues. Without a timeout, a single stuck node blocks the entire workflow. The timeout is per-node so a slow optimizer does not eat into the auditor's budget. |
| **Deterministic fallback on circuit open** | `build_fallback_optimizer_output()` calls `baseline_recommend_all()` and marks actions `[FALLBACK]` | Returning an empty result when the optimizer's circuit is open means no campaign changes are made during an API outage. The deterministic baseline produces conservative recommendations (pacing-based bid adjustments) that are safe to execute even without LLM reasoning. The `[FALLBACK]` prefix in the rationale makes the fallback visible in the audit log. |

---

## Evaluation and Experimentation

| Decision | What was chosen | Why |
|---|---|---|
| **Two-layer eval scoring** | Deterministic layer (F1 on action types, schema feasibility, policy compliance binary) + LLM judge layer (4 KPI dimensions) | Deterministic scoring is fast, cheap, and consistent — good for regression detection. But it cannot evaluate whether the *reasoning* is sound or whether the *magnitude* of a proposed change is appropriate. The LLM judge scores what deterministic metrics cannot: plan coherence, KPI alignment, and policy nuance. Neither layer alone is sufficient. |
| **LLM judge uses a separate isolated Claude call** | Judge never sees `expected_action_types`; scores on merit from goal + metrics + proposal | If the judge saw the ground truth labels it would be grading on the answer key. Isolation means the score reflects the quality of the reasoning independently of whether the exact action types match. This also means the judge can catch good proposals that used a different but equally valid action type. |
| **Golden dataset covers three categories** | 6 anomaly cases, 5 policy rule cases, 4 tool selection cases | Each category tests a different failure mode. Anomaly cases test whether the agent detects and responds to delivery problems. Policy cases test whether it respects approval thresholds. Tool selection cases test whether it picks the right lever for the goal. A dataset skewed toward one category would miss regressions in the others. |
| **Deterministic baseline as Group A** | `baseline_recommend_all()` uses hardcoded pacing/CPA rules | The baseline is intentionally simple so any advantage the agent shows comes from contextual reasoning and multi-lever coordination, not from better threshold tuning. A sophisticated baseline would make it hard to attribute improvement to the agent's RAG grounding or multi-step reasoning. The baseline also serves as the production fallback. |
| **LangSmith for A/B logging** | Both groups log to separate LangSmith projects (`AutoBid/<exp_id>-baseline`, `AutoBid/<exp_id>-agent`) | LangSmith provides full LLM message history, token counts, and tool call arguments alongside the eval scores. Logging both groups to the same platform enables direct side-by-side comparison in the LangSmith UI without building custom tooling. |

---

## Stack Choices

| Decision | What was chosen | Why |
|---|---|---|
| **FastAPI with SSE streaming** | `StreamingResponse` with `text/event-stream` for workflow events | The workflow runs for 10–60 seconds. A standard REST response would block the client for the full duration with no feedback. SSE streams each node lifecycle event and action event to the frontend as it happens, enabling the live pipeline visualization. SSE is simpler than WebSockets for a unidirectional server→client stream. |
| **SQLite with async SQLAlchemy** | `sqlite+aiosqlite` via `AsyncSession` | SQLite is zero-dependency and sufficient for a demo/portfolio project. The async driver means database writes from tool execution do not block the event loop. The schema is compatible with Postgres — swapping the `DATABASE_URL` is the only change required for production. |
| **ChromaDB for vector store** | Embedded ChromaDB with `DefaultEmbeddingFunction` | ChromaDB runs in-process with no external service dependency, making setup a `pip install` rather than spinning up a vector database server. For production scale, the retriever interface is collection-based and could be backed by Pinecone or Weaviate without changing the RAG logic. |
| **Anthropic SDK directly for judge** | `AsyncAnthropic` client in `evals/judge.py` instead of LangChain | The judge is a standalone evaluation call with no need for LangChain's message abstraction or tool-binding helpers. Using the raw SDK keeps the dependency surface minimal for the eval path and avoids LangChain tracing noise in the judge's span (the judge is not a node in the graph). |
| **`MemorySaver` checkpointer** | In-process LangGraph checkpointer | `MemorySaver` requires no external service and survives the full workflow lifecycle within a single server process. The alternative (Redis-backed `AsyncRedisSaver`) would add an operational dependency. For production, swapping the checkpointer is the only change needed to support multi-instance deployments. |
| **Next.js App Router** | React Server Components for data-fetching pages, `"use client"` only where interactivity is needed | Static pages (`/campaigns`, `/audit`, `/experiments`, `/traces`) server-render their data fetch on load — no client-side API calls needed, no loading spinners. `WorkflowConsole` is the only component that needs client-side state. This keeps the bundle small and the non-interactive pages fast. |

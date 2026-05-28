# AutoBid — Code Reference

Code snippets for every major project feature with source file references.

---

## 1. LangGraph Multi-Agent Pipeline

**`backend/agent/graph.py`**

Graph assembly, conditional routing, and dual compiled variants (with and without human approval interrupt).

```python
def build_graph() -> StateGraph:
    builder = StateGraph(AutoBidState)

    builder.add_node("planner",     planner_node)
    builder.add_node("analyst",     analyst_node)
    builder.add_node("optimizer",   optimizer_node)
    builder.add_node("auditor",     auditor_node)
    builder.add_node("gatekeeper",  gatekeeper_node)
    builder.add_node("executor",    executor_node)
    builder.add_node("reviewer",    reviewer_node)

    builder.add_edge(START,       "planner")
    builder.add_edge("planner",   "analyst")
    builder.add_edge("analyst",   "optimizer")
    builder.add_edge("optimizer", "auditor")
    builder.add_edge("auditor",   "gatekeeper")
    builder.add_conditional_edges(
        "gatekeeper", route_after_gatekeeper, ["executor", "reviewer"]
    )
    builder.add_edge("executor",  "reviewer")
    builder.add_conditional_edges(
        "reviewer", route_after_review, ["analyst", END]
    )
    return builder


_checkpointer = MemorySaver()

# Pauses before executor — requires human sign-off
_graph = build_graph().compile(
    checkpointer=_checkpointer,
    interrupt_before=["executor"],
)

# Fully-auto — executor runs without pause
_graph_auto = build_graph().compile(checkpointer=_checkpointer)


def get_graph(require_approval: bool = True):
    return _graph if require_approval else _graph_auto
```

---

## 2. Hybrid RAG Retrieval

**`backend/rag/retriever.py`**

Multi-collection retrieval fusing dense cosine similarity and BM25 keyword search via Reciprocal Rank Fusion.

```python
def retrieve(
    query: str,
    collections: list[str] | None = None,
    n_results: int = 5,
    campaign_id: Optional[str] = None,
) -> list[dict]:
    """
    For policies_playbooks: fuses dense cosine results with BM25 keyword
    results using Reciprocal Rank Fusion (RRF, k=60).
    For other collections: dense-only (semantic similarity).
    Results are de-duplicated by content hash and sorted by fused score.
    Decorated with @traceable so every call appears as a child span in LangSmith.
    """
    coll_key = tuple(collections) if collections else ()
    return _cached_retrieve(query, coll_key, n_results, campaign_id)


@lru_cache(maxsize=256)
def _cached_retrieve(query, collections, n_results, campaign_id) -> list[dict]:
    ...
    # Dense retrieval via ChromaDB
    res = collection.query(
        query_texts=[query],
        n_results=min(n_results * 2, max(collection.count(), 1)),
        include=["documents", "metadatas", "distances"],
    )
    # BM25 keyword retrieval (policies_playbooks only)
    for doc_id, bm25_score in _policy_bm25.search(query, top_k=n_results * 2):
        ...
    # Fuse via RRF if both lists are populated
    if bm25_results:
        fused = _reciprocal_rank_fusion(dense_results, bm25_results)
```

**RRF fusion (`backend/rag/retriever.py`)**

```python
def _reciprocal_rank_fusion(dense, keyword, k=60) -> list[dict]:
    """RRF score = Σ 1 / (k + rank_i)"""
    scores: dict[str, float] = {}
    docs:   dict[str, dict]  = {}

    for rank, item in enumerate(dense, start=1):
        h = hashlib.sha256(item["content"].encode()).hexdigest()
        scores[h] = scores.get(h, 0.0) + 1.0 / (k + rank)
        docs[h]   = item

    for rank, item in enumerate(keyword, start=1):
        h = hashlib.sha256(item["content"].encode()).hexdigest()
        scores[h] = scores.get(h, 0.0) + 1.0 / (k + rank)
        if h not in docs:
            docs[h] = item

    fused = []
    for h, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        fused.append({**docs[h], "relevance_score": score, "retrieval_method": "rrf"})
    return fused
```

---

## 3. Tool Safety — `@tool_guard` Decorator

**`backend/agent/guards.py`**

Three pre-execution checks applied to every campaign control tool: rate limiting, idempotency, and hard per-step change limits.

```python
def tool_guard(action_type: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args, **kwargs) -> dict:
            session_id = kwargs.get("session_id", "default")
            is_dry_run = kwargs.get("is_dry_run", False)

            # 1. Rate limit — sliding window per session
            if not is_dry_run and not _rate_limiter.allow(session_id):
                return {"error": "Rate limit exceeded", "status": "rate_limited", "audit_id": ""}

            # 2. Idempotency — SHA-256 key over (campaign_id, action_type, params)
            ikey_payload = f"{campaign_id}:{action_type}:{json.dumps(params, sort_keys=True)}"
            ikey = hashlib.sha256(ikey_payload.encode()).hexdigest()[:32]
            existing = await db.execute(
                select(AuditLog)
                .where(AuditLog.idempotency_key == ikey)
                .where(AuditLog.status.in_([ActionStatus.completed, ActionStatus.dry_run]))
                .limit(1)
            )
            if log := existing.scalar_one_or_none():
                return {"audit_id": log.id, "status": log.status, "idempotent": True}

            # 3. Hard per-step change limits
            err = _check_step_limit(action_type, before, requested)
            if err:
                return {"error": f"Hard step-limit violation: {err}", "status": "blocked"}

            return await fn(*args, **kwargs)
        return wrapper
    return decorator


# Applied to all six campaign control tools:
@tool_guard("update_bid_modifier")
async def update_bid_modifier(db, campaign_id, new_bid_modifier, ...): ...

@tool_guard("update_budget")
async def update_budget(db, campaign_id, new_daily_budget_usd, ...): ...

@tool_guard("pause_campaign")
async def pause_campaign(db, campaign_id, ...): ...
```

---

## 4. Circuit Breakers and Timeouts

**`backend/agent/reliability.py`**

Per-node circuit breakers with CLOSED/OPEN/HALF_OPEN state machine and `asyncio.wait_for` timeout wrapping.

```python
class CircuitBreaker:
    """CLOSED → OPEN after N failures; HALF_OPEN → probe after recovery window."""

    @property
    def state(self) -> str:
        # Lazy OPEN → HALF_OPEN promotion after recovery window
        if self._state == _State.OPEN:
            if time.monotonic() - self._opened_at >= self._recovery_s:
                self._state = _State.HALF_OPEN
        return self._state.value

    def record_failure(self) -> None:
        self._failures += 1
        self._opened_at = time.monotonic()
        if self._failures >= self._threshold:
            self._state = _State.OPEN


# Module-level breakers — shared across all requests
optimizer_breaker = CircuitBreaker("optimizer")
auditor_breaker   = CircuitBreaker("auditor")
planner_breaker   = CircuitBreaker("planner")
reviewer_breaker  = CircuitBreaker("reviewer")


async def call_with_guard(coro, circuit, timeout_s=None, node_name="") -> Any:
    timeout = timeout_s or settings.llm_timeout_seconds

    if circuit.is_open():
        raise CircuitOpenError(f"Circuit '{circuit.name}' is OPEN")

    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        circuit.record_success()
        return result
    except (asyncio.TimeoutError, Exception) as exc:
        circuit.record_failure()
        raise NodeTimeoutError(...) from exc
```

**Usage in optimizer node (`backend/agent/nodes/optimizer.py`)**

```python
try:
    response = await call_with_guard(
        llm.ainvoke(messages),
        circuit=optimizer_breaker,
        node_name="optimizer",
    )
except (CircuitOpenError, NodeTimeoutError) as exc:
    return build_fallback_optimizer_output(state, str(exc))
```

---

## 5. Deterministic Fallback on Circuit Open

**`backend/agent/reliability.py`**

When the optimizer's circuit is open, the system falls back to rule-based recommendations instead of failing.

```python
def build_fallback_optimizer_output(state: AutoBidState, reason: str) -> dict:
    """Call baseline_recommend_all() when optimizer circuit trips."""
    from evals.baseline import baseline_recommend_all
    raw = baseline_recommend_all(state.campaign_metrics, state.user_goal)
    actions = [
        ProposedAction(
            action_id=f"fallback_{uuid.uuid4().hex[:8]}",
            rationale=f"[FALLBACK] {reason} — {a.get('rationale','')}",
            confidence=0.6,
            priority=2,
            **{k: v for k, v in a.items() if k in ProposedAction.model_fields},
        )
        for a in raw
    ]
    return {
        "proposed_actions": actions,
        "stream_events": [{"type": "optimizer_fallback", "reason": reason, "action_count": len(actions)}],
    }
```

---

## 6. Gatekeeper Node — Structural Safety Gate

**`backend/agent/nodes/gatekeeper.py`**

LLM-free enforcement of dry-run mode, hard per-step change limits, and stale campaign references.

```python
async def gatekeeper_node(state: AutoBidState, config: RunnableConfig) -> dict:
    approved   = list(state.approved_actions)
    is_dry_run = state.dry_run
    forwarded: list[ProposedAction] = []
    gated:     list[ProposedAction] = []

    for action in approved:
        reasons: list[str] = []

        if is_dry_run:
            reasons.append("dry_run mode — execution suppressed")

        if action.campaign_id not in known_campaigns:
            reasons.append(f"campaign_id '{action.campaign_id}' not in current metrics snapshot")

        if action.action_type in STEP_HARD_LIMITS:
            err = _check_step_limit(action.action_type, before, requested)
            if err:
                reasons.append(err)

        if reasons:
            gated.append(action)
            events.append({"type": "action_gated", "reasons": reasons, ...})
        else:
            forwarded.append(action)

    return {
        "approved_actions": forwarded,   # only these reach the executor
        "gated_actions":    gated,       # surfaced in reviewer summary
        "stream_events":    events,
    }
```

---

## 7. Human-in-the-Loop Approval Gate

**`backend/agent/nodes/executor.py`**

The executor uses LangGraph's `interrupt()` to pause mid-graph and wait for human approval before writing any changes.

```python
async def executor_node(state: AutoBidState, config: RunnableConfig) -> dict:
    approved = list(state.approved_actions)
    pending  = list(state.pending_approval_actions)

    # Interrupt when auditor flagged items OR user enabled require_approval
    needs_human = pending or (state.require_approval and approved)
    if needs_human:
        all_for_human = [*pending, *approved]
        human_decision = interrupt({
            "message": f"{len(all_for_human)} action(s) ready for execution.",
            "pending_actions": [
                {"action_id": a.action_id, "action_type": a.action_type,
                 "campaign_id": a.campaign_id, "params": a.params, "rationale": a.rationale}
                for a in all_for_human
            ],
        })
        approved_ids = set(human_decision.get("approved_ids", []))
        approved = [a for a in all_for_human if a.action_id in approved_ids]

    # Execute approved actions via typed tool dispatch
    for action in approved:
        result = await _dispatch(action, common)
        ...
```

**Resume endpoint (`backend/api/agent_api.py`)**

```python
@router.post("/sessions/{session_id}/resume")
async def resume_workflow(session_id: str, req: ResumeRequest, ...):
    human_decision = {"approved_ids": req.approved_ids, "rejected_ids": req.rejected_ids}

    async for event in graph.astream_events(
        Command(resume=human_decision),
        config=thread_cfg,
        version="v2",
    ):
        ...
```

---

## 8. SSE Streaming Workflow API

**`backend/api/agent_api.py`**

Every node lifecycle event is streamed to the frontend as Server-Sent Events.

```python
@router.post("/workflow/run")
async def run_workflow(req: WorkflowRunRequest, db: AsyncSession = Depends(get_db)):
    graph = get_graph(require_approval=req.require_approval)

    async def event_stream():
        yield _sse({"type": "workflow_start", "session_id": session_id, "goal": req.goal})

        async for event in graph.astream_events(initial_state, config=thread_cfg, version="v2"):
            kind = event.get("event")
            name = event.get("name", "")
            if kind == "on_chain_start" and name in _NODE_NAMES:
                yield _sse({"type": "node_start", "node": name})
            elif kind == "on_chain_end" and name in _NODE_NAMES:
                for se in event["data"]["output"].get("stream_events", []):
                    yield _sse(se)
                yield _sse({"type": "node_end", "node": name})

        # After stream ends — check if graph paused for approval
        state_snapshot = graph.get_state(thread_cfg)
        if state_snapshot.next:
            all_actions = [
                *[_action_dict(a, True)  for a in pending_approval],
                *[_action_dict(a, False) for a in auto_approved],
            ]
            yield _sse({"type": "workflow_interrupted", "pending_actions": all_actions, ...})
        else:
            yield _sse({"type": "workflow_complete", "review_summary": ..., ...})

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
```

---

## 9. Evaluation Harness

**`backend/evals/harness.py`**

Runs optimizer → auditor → gatekeeper against golden cases using a mock DB, scoring with both deterministic metrics and LLM judge.

```python
class _MockAsyncDB:
    """Minimal async SQLAlchemy session substitute for eval runs."""
    async def execute(self, *args, **kwargs) -> _MockResult:
        return _MockResult()


class EvalResult(BaseModel):
    case_id: str
    category: str
    passed: bool
    duration_ms: int
    # Deterministic scores
    tool_selection_f1: float
    schema_feasibility: float
    policy_compliance: float
    # LLM judge scores
    plan_quality: float
    kpi_alignment: float
    judge_feasibility: float
    judge_policy_compliance: float
    judge_reasoning: str
    failures: list[str]


async def run_case(self, case: GoldenCase) -> EvalResult:
    state = AutoBidState(
        user_goal=case.user_goal,
        campaign_metrics=case.campaign_metrics,
        rag_context=EVAL_POLICY_CONTEXT,
        ...
    )
    config = _mock_config()

    # Run the three-node pipeline
    opt_out  = await optimizer_node(state, config)
    aud_out  = await auditor_node(state.model_copy(update=opt_out), config)
    gate_out = await gatekeeper_node(state.model_copy(update={**opt_out, **aud_out}), config)

    # Deterministic F1 over action types
    predicted = set(a.action_type for a in proposed)
    expected  = set(case.expected_action_types)
    f1 = _f1(predicted, expected)

    # LLM judge
    scores = await judge_proposal(case.user_goal, case.campaign_metrics, proposed, ...)
```

---

## 10. LLM-as-a-Judge

**`backend/evals/judge.py`**

Independent Claude call that scores optimizer output on four KPI dimensions using a forced tool call.

```python
_JUDGE_TOOL = {
    "name": "score_proposal",
    "input_schema": {
        "properties": {
            "plan_quality":      {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "kpi_alignment":     {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "feasibility":       {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "policy_compliance": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "reasoning":         {"type": "string"},
        }
    }
}


async def judge_proposal(user_goal, campaign_metrics, proposed_actions, ...) -> JudgeScores:
    response = await _client.messages.create(
        model=settings.claude_model,
        system=JUDGE_SYSTEM,
        tools=[_JUDGE_TOOL],
        tool_choice={"type": "tool", "name": "score_proposal"},
        messages=[{"role": "user", "content": _build_prompt(...)}],
    )
    scores = response.content[0].input
    return JudgeScores(**scores)
```

---

## 11. A/B Experimentation (LangSmith)

**`backend/evals/langsmith_runner.py`**

Runs agent vs. deterministic baseline concurrently, scores both groups with the LLM judge, and logs results to LangSmith.

```python
class CaseScores(BaseModel):
    tool_selection_f1: float
    schema_feasibility: float
    kpi_alignment: float
    plan_quality: float

    @property
    def composite(self) -> float:
        return (0.35 * self.tool_selection_f1
              + 0.25 * self.schema_feasibility
              + 0.25 * self.kpi_alignment
              + 0.15 * self.plan_quality)


async def run_ab_experiment(category=None, experiment_name=None) -> ExperimentResult:
    cases = [c for c in GOLDEN_CASES if not category or c.category == category]

    # Run both groups concurrently
    baseline_results, agent_results = await asyncio.gather(
        asyncio.gather(*[_run_baseline_case(c) for c in cases]),
        asyncio.gather(*[_run_agent_case(c)    for c in cases]),
    )

    # Log to LangSmith under separate projects for side-by-side comparison
    if langsmith_client:
        for group, project_suffix, results in [
            ("baseline", f"{exp_id}-baseline", baseline_results),
            ("agent",    f"{exp_id}-agent",    agent_results),
        ]:
            for case, scores in zip(cases, results):
                langsmith_client.create_run(
                    project_name=f"AutoBid/{project_suffix}",
                    outputs={"composite": scores.composite, ...},
                )
```

---

## 12. Deterministic Baseline Optimizer

**`backend/evals/baseline.py`**

Rule-based Group A for the A/B experiment — also used as the fallback when the circuit breaker opens.

```python
def baseline_recommend(campaign_id: str, metrics: dict, goal: str = "") -> list[dict]:
    pacing   = metrics.get("pacing_rate", 1.0)
    bid      = metrics.get("bid_modifier", 1.0)
    cpa      = metrics.get("cpa_usd")
    target_cpa = metrics.get("target_cpa")

    bid_delta = 0.0

    # CPA signal takes precedence over pacing
    if cpa and target_cpa:
        cpa_ratio = cpa / target_cpa
        if cpa_ratio > 1.20:
            bid_delta = -min((cpa_ratio - 1.0) * 0.5, 0.15)  # reduce bid, cap at -15%
        elif cpa_ratio < 0.85 and pacing < 0.95:
            bid_delta = 0.07                                    # raise bid for volume

    # Pacing signal (only if CPA didn't set a delta)
    if bid_delta == 0.0:
        if pacing < 0.75:   bid_delta =  0.10   # severe under-pacing → +10%
        elif pacing < 0.85: bid_delta =  0.07   # moderate under-pacing → +7%
        elif pacing > 1.20: bid_delta = -0.10   # over-pacing → -10%

    if bid_delta != 0.0:
        actions.append({
            "action_type": "update_bid_modifier",
            "campaign_id": campaign_id,
            "params": {"new_bid_modifier": round(bid + bid * bid_delta, 4)},
            "rationale": bid_rationale,
            "confidence": 0.75,
        })
```

---

## 13. LangSmith End-to-End Tracing

**`backend/agent/langsmith_tracing.py`**

Activates full pipeline tracing at startup by setting LangChain environment variables.

```python
def setup_langsmith_tracing() -> bool:
    """Called once from main.py lifespan. Sets env vars before first graph run."""
    api_key = getattr(settings, "langsmith_api_key", "")
    if not api_key:
        return False

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"]    = api_key
    os.environ["LANGCHAIN_PROJECT"]    = settings.langchain_project
    return True
```

**RAG retrieval tracing (`backend/rag/retriever.py`)**

```python
# @traceable makes retrieve() a named child span in LangSmith,
# capturing query, collections, result count, and latency.
try:
    from langsmith import traceable as _traceable
except ImportError:
    def _traceable(**_kw):
        def _wrap(fn): return fn
        return _wrap

@_traceable(run_type="retriever", name="rag_retrieve",
            metadata={"strategy": "hybrid-rrf"})
def retrieve(query, collections=None, n_results=5, campaign_id=None) -> list[dict]:
    ...
```

---

## 14. Session State Persistence (Frontend)

**`frontend/components/agent/WorkflowConsole.tsx`**

Full workflow state is persisted to `sessionStorage` so navigating away and returning restores the event log, pipeline visualization, plan steps, audit findings, and any pending approval gate.

```typescript
const STORAGE_KEY = "autobid:workflow";

interface PersistedState {
  goal: string;
  events: WorkflowEvent[];
  nodeStatuses: Record<WorkflowNodeName, NodeStatus>;
  planSteps: PlanStep[];
  findings: AuditFinding[];
  approval: ApprovalGate | null;
  selectedApprovals: string[];
  summary: { text: string; complete: boolean } | null;
  sessionId: string | null;
}

function loadSaved(): PersistedState | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as PersistedState) : null;
  } catch { return null; }
}

// Seed all useState hooks from sessionStorage on first render
const saved = useRef<PersistedState | null>(null);
if (saved.current === null) saved.current = loadSaved();
const s = saved.current;
const [events, setEvents] = useState<WorkflowEvent[]>(s?.events ?? []);
const [approval, setApproval] = useState<ApprovalGate | null>(s?.approval ?? null);

// Persist on every state change
useEffect(() => {
  const state: PersistedState = {
    goal, events, nodeStatuses, planSteps, findings,
    approval, selectedApprovals: [...selectedApprovals],
    summary, sessionId,
  };
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch {}
}, [goal, events, nodeStatuses, planSteps, findings, approval, selectedApprovals, summary, sessionId]);
```

---

## 15. Pydantic State Model

**`backend/agent/state.py`**

Single typed state object shared across all LangGraph nodes. Annotated reducer fields (`messages`, `stream_events`, `errors`) are append-only.

```python
class AutoBidState(BaseModel):
    # Input
    user_goal:        str  = ""
    dry_run:          bool = False
    require_approval: bool = True
    session_id:       str  = ""
    trace_id:         str  = ""

    # Planning
    plan_steps:       list[PlanStep]      = Field(default_factory=list)
    current_step_idx: int                 = 0

    # Analysis
    campaign_metrics: dict                = Field(default_factory=dict)
    rag_context:      str                 = ""
    rag_sources:      list[str]           = Field(default_factory=list)

    # Optimization → Audit → Execution
    proposed_actions:         list[ProposedAction]  = Field(default_factory=list)
    approved_actions:         list[ProposedAction]  = Field(default_factory=list)
    blocked_actions:          list[ProposedAction]  = Field(default_factory=list)
    pending_approval_actions: list[ProposedAction]  = Field(default_factory=list)
    gated_actions:            list[ProposedAction]  = Field(default_factory=list)
    executed_results:         list[ExecutedResult]  = Field(default_factory=list)

    # Review
    review_summary:       str  = ""
    optimization_complete: bool = False

    # Append-only (LangGraph reducer)
    messages:     Annotated[list, operator.add]       = Field(default_factory=list)
    stream_events: Annotated[list[dict], operator.add] = Field(default_factory=list)
    errors:       Annotated[list[str], operator.add]  = Field(default_factory=list)
```

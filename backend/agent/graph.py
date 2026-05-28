"""
AutoBid LangGraph — stateful multi-agent workflow.

Flow:
  START → planner → analyst → optimizer → auditor → gatekeeper
        → [has_actions?] → executor → reviewer
        → [complete?] → END | analyst (next iteration)

Gatekeeper sits between auditor and executor and is the structural
enforcement point for dry-run mode and hard per-step change limits.
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from agent.state import AutoBidState
from agent.nodes import (
    planner_node,
    analyst_node,
    optimizer_node,
    auditor_node,
    gatekeeper_node,
    executor_node,
    reviewer_node,
)


# ── Conditional routing ───────────────────────────────────────────────────────

def route_after_gatekeeper(state: AutoBidState) -> str:
    """Route to executor only if gatekeeper forwarded any actions."""
    # Pydantic attribute access — NOT state.get(...)
    if state.approved_actions or state.pending_approval_actions:
        return "executor"
    return "reviewer"


def route_after_review(state: AutoBidState) -> str:
    """Loop back for another iteration, or finish."""
    if state.optimization_complete:
        return END
    if state.current_step_idx >= len(state.plan_steps):
        return END
    return "analyst"


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    builder = StateGraph(AutoBidState)

    builder.add_node("planner",     planner_node)
    builder.add_node("analyst",     analyst_node)
    builder.add_node("optimizer",   optimizer_node)
    builder.add_node("auditor",     auditor_node)
    builder.add_node("gatekeeper",  gatekeeper_node)   # NEW — between auditor and executor
    builder.add_node("executor",    executor_node)
    builder.add_node("reviewer",    reviewer_node)

    builder.add_edge(START,       "planner")
    builder.add_edge("planner",   "analyst")
    builder.add_edge("analyst",   "optimizer")
    builder.add_edge("optimizer", "auditor")
    builder.add_edge("auditor",   "gatekeeper")        # always runs after auditor
    builder.add_conditional_edges(
        "gatekeeper", route_after_gatekeeper, ["executor", "reviewer"]
    )
    builder.add_edge("executor",  "reviewer")
    builder.add_conditional_edges(
        "reviewer", route_after_review, ["analyst", END]
    )

    return builder


# ── Compiled graphs ───────────────────────────────────────────────────────────

_checkpointer = MemorySaver()

# Pauses at executor when pending_approval_actions is non-empty
_graph = build_graph().compile(
    checkpointer=_checkpointer,
    interrupt_before=["executor"],
)

# Fully-auto — executor runs without pause (approval policy still blocks)
_graph_auto = build_graph().compile(checkpointer=_checkpointer)


def get_graph(require_approval: bool = True):
    return _graph if require_approval else _graph_auto


def make_thread_config(session_id: str, db) -> dict:
    return {"configurable": {"thread_id": session_id, "db": db}}


def make_initial_state(
    user_goal: str,
    session_id: str,
    trace_id: str,
    dry_run: bool = False,
    require_approval: bool = True,
) -> AutoBidState:
    return AutoBidState(
        user_goal=user_goal,
        dry_run=dry_run,
        require_approval=require_approval,
        session_id=session_id,
        trace_id=trace_id,
    )

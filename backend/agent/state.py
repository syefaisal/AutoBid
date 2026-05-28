"""
AutoBid LangGraph state — Pydantic BaseModel so every field is validated
on write, not just at construction time.  LangGraph reads the Annotated
reducers from field metadata; Pydantic uses the inner type for validation.
"""
from __future__ import annotations

import operator
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.schemas import ActionType


class PlanStep(BaseModel):
    step_id: str
    title: str
    description: str
    step_type: Literal[
        "analyze", "optimize_bid", "update_budget",
        "update_targeting", "update_supply", "route_creative", "review"
    ]
    campaign_ids: list[str] = Field(default_factory=list)
    priority: Literal["high", "medium", "low"] = "medium"
    status: Literal["pending", "in_progress", "completed", "skipped"] = "pending"


class ProposedAction(BaseModel):
    action_id: str
    action_type: ActionType
    campaign_id: str
    params: dict = Field(
        default_factory=dict,
        description="Validated param dict — populated by the Optimizer from the "
                    "typed Pydantic schema for this action_type.",
    )
    rationale: str
    expected_impact: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    priority: int = Field(ge=1)


class AuditFinding(BaseModel):
    finding_id: str
    action_id: str
    severity: Literal["pass", "info", "warning", "block"]
    finding: str
    policy_source: str
    recommendation: str
    requires_human_approval: bool


class ExecutedResult(BaseModel):
    action_id: str
    action_type: str
    campaign_id: str
    status: Literal["completed", "dry_run", "pending_approval", "failed", "unknown"]
    audit_id: str
    result: dict = Field(default_factory=dict)


class AutoBidState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # ── Input ─────────────────────────────────────────────────────────────────
    user_goal: str = ""
    dry_run: bool = False
    require_approval: bool = True
    session_id: str = ""
    trace_id: str = ""

    # ── Planning ──────────────────────────────────────────────────────────────
    plan_title: str = ""
    plan_steps: list[PlanStep] = Field(default_factory=list)
    current_step_idx: int = 0

    # ── Analysis ──────────────────────────────────────────────────────────────
    campaign_metrics: dict = Field(default_factory=dict)
    rag_context: str = ""
    rag_sources: list[str] = Field(default_factory=list)

    # ── Optimization ──────────────────────────────────────────────────────────
    proposed_actions: list[ProposedAction] = Field(default_factory=list)

    # ── Audit ─────────────────────────────────────────────────────────────────
    audit_findings: list[AuditFinding] = Field(default_factory=list)
    approved_actions: list[ProposedAction] = Field(default_factory=list)
    blocked_actions: list[ProposedAction] = Field(default_factory=list)
    pending_approval_actions: list[ProposedAction] = Field(default_factory=list)

    # ── Gatekeeper ────────────────────────────────────────────────────────────
    # Actions that passed the auditor but were stopped by the gatekeeper
    # (dry-run suppression, hard step-limit violations, stale campaign refs).
    gated_actions: list[ProposedAction] = Field(default_factory=list)

    # ── Execution ─────────────────────────────────────────────────────────────
    executed_results: list[ExecutedResult] = Field(default_factory=list)

    # ── Review ────────────────────────────────────────────────────────────────
    review_summary: str = ""
    optimization_complete: bool = False
    next_iteration_notes: str = ""

    # ── Append-only via LangGraph reducer ─────────────────────────────────────
    messages: Annotated[list, operator.add] = Field(default_factory=list)
    stream_events: Annotated[list[dict], operator.add] = Field(default_factory=list)
    errors: Annotated[list[str], operator.add] = Field(default_factory=list)

    iteration_count: int = 1

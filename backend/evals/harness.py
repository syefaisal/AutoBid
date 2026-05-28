"""
EvalHarness — runs golden cases through the optimizer → auditor → gatekeeper
pipeline and scores outputs.

Scoring is two-layer:
  deterministic   — tool_selection F1 (recall × precision), schema feasibility,
                    policy compliance (approval/block checks)
  LLM judge       — plan_quality, kpi_alignment, feasibility (judge.py)

No real DB required: a MockAsyncDB satisfies query_telemetry_aggregates if the
optimizer calls it; the metrics state is pre-populated so it typically won't.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from pydantic import BaseModel

from agent.state import AutoBidState, PlanStep
from agent.nodes.optimizer import optimizer_node
from agent.nodes.auditor import auditor_node
from agent.nodes.gatekeeper import gatekeeper_node
from agent.schemas import parse_action_params
from pydantic import ValidationError as PydanticValidationError

from evals.dataset import GoldenCase, GOLDEN_CASES, CASES_BY_ID
from evals.judge import judge_proposal


# ── Mock DB for eval runs ─────────────────────────────────────────────────────

class _MockResult:
    def fetchall(self) -> list:
        return []


class _MockAsyncDB:
    """Minimal async SQLAlchemy session substitute used in eval runs."""

    async def execute(self, *args: Any, **kwargs: Any) -> _MockResult:
        return _MockResult()


def _mock_config(session_id: str = "eval") -> dict:
    return {"configurable": {"thread_id": session_id, "db": _MockAsyncDB()}}


# ── Result models ─────────────────────────────────────────────────────────────

class EvalResult(BaseModel):
    case_id: str
    category: str
    passed: bool
    duration_ms: int

    # Deterministic scores
    tool_selection_f1: float
    schema_feasibility: float     # fraction of proposed actions with valid params
    policy_compliance: float      # 0 or 1 — did approval/block expectations match?

    # LLM judge scores
    plan_quality: float
    kpi_alignment: float
    judge_feasibility: float
    judge_policy_compliance: float
    judge_reasoning: str

    # Raw outputs
    proposed_count: int
    approved_count: int
    blocked_count: int
    pending_approval_count: int
    gated_count: int
    proposed_action_types: list[str]

    failures: list[str]


class EvalSuiteResult(BaseModel):
    total: int
    passed: int
    failed: int
    pass_rate: float
    duration_ms: int
    scores: dict[str, float]      # avg of each numeric dimension
    results: list[EvalResult]


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _f1(predicted: set[str], expected: set[str]) -> float:
    if not expected:
        return 1.0
    if not predicted:
        return 0.0
    tp = len(predicted & expected)
    precision = tp / len(predicted)
    recall = tp / len(expected)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _schema_feasibility(proposed_actions: list) -> float:
    if not proposed_actions:
        return 1.0
    valid = 0
    for a in proposed_actions:
        try:
            parse_action_params(a.action_type, a.params)
            valid += 1
        except (PydanticValidationError, ValueError):
            pass
    return valid / len(proposed_actions)


def _policy_compliance_score(case: GoldenCase, state: AutoBidState) -> float:
    """
    Binary check: did the pipeline match expected approval/block outcomes?
    Returns 1.0 if expectations are met, 0.0 otherwise.
    """
    approval_ok = True
    block_ok = True

    if case.should_trigger_approval and not state.pending_approval_actions:
        approval_ok = False
    if case.should_be_blocked_by_audit and not state.blocked_actions:
        block_ok = False

    return 1.0 if (approval_ok and block_ok) else 0.0


# ── EvalHarness ───────────────────────────────────────────────────────────────

class EvalHarness:
    """Run golden cases through the optimizer → auditor → gatekeeper pipeline."""

    async def run_case(self, case: GoldenCase) -> EvalResult:
        t0 = time.monotonic()
        failures: list[str] = []

        # Build a synthetic state from the golden case
        synthetic_step = PlanStep(
            step_id="eval_step_01",
            title="Evaluate",
            description=case.user_goal,
            step_type="optimize_bid",
            campaign_ids=list(case.campaign_metrics.keys()),
            priority="high",
        )
        state = AutoBidState(
            user_goal=case.user_goal,
            dry_run=False,
            session_id=f"eval_{case.case_id}",
            trace_id=f"eval_trace_{case.case_id}",
            campaign_metrics=case.campaign_metrics,
            rag_context=case.rag_context,
            plan_steps=[synthetic_step],
            current_step_idx=0,
        )

        config = _mock_config(case.case_id)

        # ── Optimizer ─────────────────────────────────────────────────────────
        optimizer_out = await optimizer_node(state, config)
        state = state.model_copy(update={
            k: v for k, v in optimizer_out.items()
            if k in AutoBidState.model_fields
        })

        # ── Auditor ───────────────────────────────────────────────────────────
        auditor_out = await auditor_node(state, config)
        state = state.model_copy(update={
            k: v for k, v in auditor_out.items()
            if k in AutoBidState.model_fields
        })

        # ── Gatekeeper ────────────────────────────────────────────────────────
        gatekeeper_out = await gatekeeper_node(state, config)
        state = state.model_copy(update={
            k: v for k, v in gatekeeper_out.items()
            if k in AutoBidState.model_fields
        })

        proposed = state.proposed_actions
        proposed_types = {a.action_type for a in proposed}
        expected_types = set(case.expected_action_types)
        forbidden_types = set(case.forbidden_action_types)

        # ── Deterministic scoring ─────────────────────────────────────────────
        tool_f1 = _f1(proposed_types, expected_types)
        schema_feas = _schema_feasibility(proposed)
        policy_score = _policy_compliance_score(case, state)

        # Check forbidden types
        forbidden_found = proposed_types & forbidden_types
        if forbidden_found:
            failures.append(
                f"Forbidden action types proposed: {sorted(forbidden_found)}"
            )

        if tool_f1 < case.min_tool_selection_f1:
            failures.append(
                f"tool_selection_f1 {tool_f1:.2f} < threshold {case.min_tool_selection_f1}"
            )

        if schema_feas < case.min_feasibility:
            failures.append(
                f"schema_feasibility {schema_feas:.2f} < threshold {case.min_feasibility}"
            )

        if case.should_trigger_approval and not state.pending_approval_actions:
            failures.append("Expected ≥1 pending_approval action but got none")

        if case.should_be_blocked_by_audit and not state.blocked_actions:
            failures.append("Expected ≥1 blocked action but got none")

        # ── LLM judge scoring ─────────────────────────────────────────────────
        judge_scores = await judge_proposal(
            user_goal=case.user_goal,
            campaign_metrics=case.campaign_metrics,
            proposed_actions=[
                {
                    "action_type": a.action_type,
                    "campaign_id": a.campaign_id,
                    "params": a.params,
                    "rationale": a.rationale,
                    "confidence": a.confidence,
                }
                for a in proposed
            ],
            rag_context=case.rag_context,
            cpa_target_usd=case.cpa_target_usd,
            roas_target=case.roas_target,
            pacing_target=case.pacing_target,
        )

        if judge_scores.kpi_alignment < case.min_kpi_alignment:
            failures.append(
                f"kpi_alignment {judge_scores.kpi_alignment:.2f} < threshold {case.min_kpi_alignment}"
            )

        duration_ms = int((time.monotonic() - t0) * 1000)

        return EvalResult(
            case_id=case.case_id,
            category=case.category,
            passed=len(failures) == 0,
            duration_ms=duration_ms,
            tool_selection_f1=round(tool_f1, 3),
            schema_feasibility=round(schema_feas, 3),
            policy_compliance=round(policy_score, 3),
            plan_quality=round(judge_scores.plan_quality, 3),
            kpi_alignment=round(judge_scores.kpi_alignment, 3),
            judge_feasibility=round(judge_scores.feasibility, 3),
            judge_policy_compliance=round(judge_scores.policy_compliance, 3),
            judge_reasoning=judge_scores.reasoning,
            proposed_count=len(proposed),
            approved_count=len(state.approved_actions),
            blocked_count=len(state.blocked_actions),
            pending_approval_count=len(state.pending_approval_actions),
            gated_count=len(state.gated_actions),
            proposed_action_types=sorted(proposed_types),
            failures=failures,
        )

    async def run_suite(
        self,
        case_ids: list[str] | None = None,
        category: str | None = None,
    ) -> EvalSuiteResult:
        t0 = time.monotonic()

        cases = list(GOLDEN_CASES)
        if case_ids:
            cases = [c for c in cases if c.case_id in case_ids]
        if category:
            cases = [c for c in cases if c.category == category]

        # Run cases concurrently — each is an independent LLM session
        results = await asyncio.gather(*[self.run_case(c) for c in cases])

        passed = sum(1 for r in results if r.passed)
        total = len(results)
        numeric_fields = [
            "tool_selection_f1", "schema_feasibility", "policy_compliance",
            "plan_quality", "kpi_alignment", "judge_feasibility",
            "judge_policy_compliance",
        ]
        avg_scores = {
            f: round(sum(getattr(r, f) for r in results) / max(total, 1), 3)
            for f in numeric_fields
        }

        return EvalSuiteResult(
            total=total,
            passed=passed,
            failed=total - passed,
            pass_rate=round(passed / max(total, 1), 3),
            duration_ms=int((time.monotonic() - t0) * 1000),
            scores=avg_scores,
            results=list(results),
        )

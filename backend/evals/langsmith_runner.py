"""
LangSmith A/B experiment runner.

Compares two groups on the anomaly golden cases:
  Group A (control)   — deterministic rule-based baseline (evals/baseline.py)
  Group B (treatment) — autonomous LangGraph agent optimizer

Three scorers:
  tool_selection_f1    — F1 of proposed action types vs expected (deterministic)
  schema_feasibility   — fraction of proposed params that pass Pydantic validation
  kpi_alignment        — LLM judge score for direction + magnitude vs KPI targets

Results are logged to LangSmith as a pair of projects
  "AutoBid/<exp_id>-baseline"  and  "AutoBid/<exp_id>-agent"
so the two experiments can be compared side-by-side in the LangSmith UI.

LangSmith API key is optional — if not configured the experiment runs locally
and scores are returned without remote logging.
"""
from __future__ import annotations

import asyncio
import time

from pydantic import BaseModel

from evals.dataset import GOLDEN_CASES, GoldenCase, EVAL_POLICY_CONTEXT
from evals.baseline import baseline_recommend_all
from evals.harness import _f1, _schema_feasibility, _mock_config
from evals.judge import judge_proposal
from agent.nodes.optimizer import optimizer_node
from agent.state import AutoBidState, PlanStep
from config import settings


# ── Score models ──────────────────────────────────────────────────────────────

class CaseScores(BaseModel):
    tool_selection_f1: float
    schema_feasibility: float
    kpi_alignment: float
    plan_quality: float

    @property
    def composite(self) -> float:
        return round(
            0.35 * self.tool_selection_f1
            + 0.25 * self.schema_feasibility
            + 0.25 * self.kpi_alignment
            + 0.15 * self.plan_quality,
            3,
        )


class GroupResult(BaseModel):
    group: str
    case_id: str
    action_types: list[str]
    scores: CaseScores
    actions: list[dict]


class ExperimentResult(BaseModel):
    experiment_id: str
    cases_run: int
    group_a_composite: float
    group_b_composite: float
    delta_composite: float           # B - A (positive = agent wins)
    group_a_results: list[GroupResult]
    group_b_results: list[GroupResult]
    langsmith_logged: bool
    langsmith_project: str | None
    duration_ms: int


# ── Group runners ─────────────────────────────────────────────────────────────

async def _run_baseline_case(case: GoldenCase) -> dict:
    """Group A: deterministic rule-based recommendations."""
    actions = baseline_recommend_all(case.campaign_metrics, case.user_goal)
    return {
        "actions": actions,
        "action_types": sorted({a["action_type"] for a in actions}),
    }


async def _run_agent_case(case: GoldenCase) -> dict:
    """Group B: LangGraph optimizer node recommendations."""
    step = PlanStep(
        step_id="ab_step_01",
        title="Optimize",
        description=case.user_goal,
        step_type="optimize_bid",
        campaign_ids=list(case.campaign_metrics.keys()),
        priority="high",
    )
    state = AutoBidState(
        user_goal=case.user_goal,
        dry_run=False,
        session_id=f"ab_{case.case_id}",
        trace_id=f"ab_trace_{case.case_id}",
        campaign_metrics=case.campaign_metrics,
        rag_context=case.rag_context,
        plan_steps=[step],
        current_step_idx=0,
    )
    out = await optimizer_node(state, _mock_config(f"ab_{case.case_id}"))
    proposed = out.get("proposed_actions", [])
    return {
        "actions": [
            {
                "action_type": a.action_type,
                "campaign_id": a.campaign_id,
                "params": a.params,
                "rationale": a.rationale,
                "confidence": a.confidence,
            }
            for a in proposed
        ],
        "action_types": sorted({a.action_type for a in proposed}),
    }


async def _score_output(case: GoldenCase, output: dict) -> CaseScores:
    from agent.state import ProposedAction

    predicted = {a["action_type"] for a in output.get("actions", [])}
    expected = set(case.expected_action_types)
    tool_f1 = _f1(predicted, expected)

    fake_actions = []
    for a in output.get("actions", []):
        try:
            fake_actions.append(
                ProposedAction(
                    action_id="eval",
                    action_type=a["action_type"],
                    campaign_id=a.get("campaign_id", ""),
                    params=a.get("params", {}),
                    rationale=a.get("rationale", ""),
                    confidence=a.get("confidence", 0.7),
                    priority=1,
                )
            )
        except Exception:
            pass
    feas = _schema_feasibility(fake_actions)

    judge_scores = await judge_proposal(
        user_goal=case.user_goal,
        campaign_metrics=case.campaign_metrics,
        proposed_actions=output.get("actions", []),
        rag_context=case.rag_context,
        cpa_target_usd=case.cpa_target_usd,
        roas_target=case.roas_target,
        pacing_target=case.pacing_target,
    )

    return CaseScores(
        tool_selection_f1=round(tool_f1, 3),
        schema_feasibility=round(feas, 3),
        kpi_alignment=round(judge_scores.kpi_alignment, 3),
        plan_quality=round(judge_scores.plan_quality, 3),
    )


# ── LangSmith logger ──────────────────────────────────────────────────────────

def _log_to_langsmith(
    project_name: str,
    group: str,
    case: GoldenCase,
    output: dict,
    scores: CaseScores,
    client: object,
) -> None:
    """Log one result row as a LangSmith run under *project_name*."""
    client.create_run(  # type: ignore[attr-defined]
        name=f"{case.case_id}",
        run_type="chain",
        inputs={
            "case_id": case.case_id,
            "category": case.category,
            "user_goal": case.user_goal,
            "campaign_metrics": case.campaign_metrics,
            "expected_action_types": case.expected_action_types,
        },
        outputs={
            "action_types": output.get("action_types", []),
            "actions": output.get("actions", []),
        },
        extra={
            "metadata": {
                "group": group,
                "scores": scores.model_dump(),
                "composite": scores.composite,
            }
        },
        project_name=project_name,
        end_time=time.time(),
    )


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_ab_experiment(
    category: str = "anomaly",
    experiment_name: str | None = None,
) -> ExperimentResult:
    """
    Run the A/B experiment on golden cases of the given category.

    Both groups run concurrently; scoring also concurrent.
    Results logged to LangSmith if LANGSMITH_API_KEY is configured.
    """
    t0 = time.monotonic()
    exp_id = experiment_name or f"ab_{int(time.time())}"

    cases = [c for c in GOLDEN_CASES if c.category == category]

    # ── Run both groups concurrently ──────────────────────────────────────────
    a_outputs, b_outputs = await asyncio.gather(
        asyncio.gather(*[_run_baseline_case(c) for c in cases]),
        asyncio.gather(*[_run_agent_case(c) for c in cases]),
    )

    # ── Score concurrently ────────────────────────────────────────────────────
    a_scores, b_scores = await asyncio.gather(
        asyncio.gather(*[_score_output(c, o) for c, o in zip(cases, a_outputs)]),
        asyncio.gather(*[_score_output(c, o) for c, o in zip(cases, b_outputs)]),
    )

    # ── Build result objects ──────────────────────────────────────────────────
    a_results = [
        GroupResult(
            group="baseline",
            case_id=case.case_id,
            action_types=out.get("action_types", []),
            scores=sc,
            actions=out.get("actions", []),
        )
        for case, out, sc in zip(cases, a_outputs, a_scores)
    ]
    b_results = [
        GroupResult(
            group="agent",
            case_id=case.case_id,
            action_types=out.get("action_types", []),
            scores=sc,
            actions=out.get("actions", []),
        )
        for case, out, sc in zip(cases, b_outputs, b_scores)
    ]

    # ── LangSmith logging (optional) ──────────────────────────────────────────
    langsmith_logged = False
    langsmith_project: str | None = None
    api_key = getattr(settings, "langsmith_api_key", "")

    if api_key:
        try:
            from langsmith import Client  # type: ignore[import]
            client = Client(api_key=api_key)
            baseline_project = f"AutoBid/{exp_id}-baseline"
            agent_project = f"AutoBid/{exp_id}-agent"
            langsmith_project = f"AutoBid/{exp_id}"

            for case, out, sc in zip(cases, a_outputs, a_scores):
                _log_to_langsmith(baseline_project, "baseline", case, out, sc, client)

            for case, out, sc in zip(cases, b_outputs, b_scores):
                _log_to_langsmith(agent_project, "agent", case, out, sc, client)

            langsmith_logged = True
        except Exception:
            pass

    # ── Aggregate ─────────────────────────────────────────────────────────────
    def _avg_composite(results: list[GroupResult]) -> float:
        if not results:
            return 0.0
        return round(sum(r.scores.composite for r in results) / len(results), 3)

    return ExperimentResult(
        experiment_id=exp_id,
        cases_run=len(cases),
        group_a_composite=_avg_composite(a_results),
        group_b_composite=_avg_composite(b_results),
        delta_composite=round(_avg_composite(b_results) - _avg_composite(a_results), 3),
        group_a_results=a_results,
        group_b_results=b_results,
        langsmith_logged=langsmith_logged,
        langsmith_project=langsmith_project,
        duration_ms=int((time.monotonic() - t0) * 1000),
    )

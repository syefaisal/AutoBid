"""
LLM-as-a-Judge — independent scoring of optimizer output against KPI goals.

Uses a separate Claude call (isolated from the optimizer's context) to score
four dimensions:
  plan_quality      — coherence of the proposed action set relative to the goal
  kpi_alignment     — direction and magnitude of proposed params vs KPI targets
  feasibility       — params within valid ranges and conservative bounds
  policy_compliance — adherence to approval gates and hard limits

The judge never sees the expected_action_types; it scores on merit alone.
"""
from __future__ import annotations

import json
from pydantic import BaseModel
from anthropic import AsyncAnthropic

from config import settings

_client = AsyncAnthropic(api_key=settings.anthropic_api_key)

JUDGE_SYSTEM = """\
You are AutoBid Quality Judge — an independent evaluator of AI-generated campaign
optimization recommendations.

You receive a user goal, KPI targets, policy rules, and a set of proposed campaign
actions.  Score the proposal on four dimensions.  Be objective and rigorous.
A proposal that correctly identifies the problem but picks the wrong lever should
score low on kpi_alignment even if feasibility is high.

Scoring rubric:
  plan_quality     : 0.0 awful, 0.5 partial, 1.0 complete & well-reasoned
  kpi_alignment    : 0.0 wrong direction, 0.5 correct direction wrong magnitude, 1.0 right direction+magnitude
  feasibility      : 0.0 params out of bounds, 0.5 borderline, 1.0 all params valid & conservative
  policy_compliance: 0.0 clear violation, 0.5 borderline, 1.0 fully compliant or no issues

Always call the `score_proposal` tool — do not emit free text.
"""

_JUDGE_TOOL = {
    "name": "score_proposal",
    "description": "Emit structured quality scores for the proposed campaign actions.",
    "input_schema": {
        "type": "object",
        "required": [
            "plan_quality", "kpi_alignment", "feasibility",
            "policy_compliance", "reasoning",
        ],
        "properties": {
            "plan_quality": {
                "type": "number", "minimum": 0.0, "maximum": 1.0,
                "description": "Does the action set coherently address the stated goal?",
            },
            "kpi_alignment": {
                "type": "number", "minimum": 0.0, "maximum": 1.0,
                "description": "Are proposed param changes directionally correct and well-sized vs KPI targets?",
            },
            "feasibility": {
                "type": "number", "minimum": 0.0, "maximum": 1.0,
                "description": "Are all proposed params within valid ranges and conservatively sized?",
            },
            "policy_compliance": {
                "type": "number", "minimum": 0.0, "maximum": 1.0,
                "description": "Do the proposals respect approval gates, bid floor/ceiling, and hard limits?",
            },
            "reasoning": {
                "type": "string",
                "description": "2-4 sentence explanation of the scores, citing specific values.",
            },
        },
    },
}


class JudgeScores(BaseModel):
    plan_quality: float
    kpi_alignment: float
    feasibility: float
    policy_compliance: float
    reasoning: str


_FALLBACK = JudgeScores(
    plan_quality=0.0,
    kpi_alignment=0.0,
    feasibility=0.0,
    policy_compliance=0.0,
    reasoning="Judge call failed — no scores available.",
)


async def judge_proposal(
    user_goal: str,
    campaign_metrics: dict,
    proposed_actions: list[dict],
    rag_context: str = "",
    cpa_target_usd: float | None = None,
    roas_target: float | None = None,
    pacing_target: float = 1.0,
) -> JudgeScores:
    """
    Score a set of proposed actions against the user goal and KPI targets.

    *proposed_actions* should be a list of dicts with keys:
    action_type, campaign_id, params, rationale, confidence.
    """
    if not proposed_actions:
        return JudgeScores(
            plan_quality=0.0,
            kpi_alignment=0.0,
            feasibility=1.0,
            policy_compliance=1.0,
            reasoning="No actions proposed — plan_quality and kpi_alignment are 0.",
        )

    kpi_lines = []
    if cpa_target_usd is not None:
        kpi_lines.append(f"CPA target: ${cpa_target_usd:.2f}")
    if roas_target is not None:
        kpi_lines.append(f"ROAS target: {roas_target:.2f}")
    kpi_lines.append(f"Pacing target: {pacing_target:.2f}")

    metrics_summary = json.dumps(campaign_metrics, indent=2)
    actions_summary = json.dumps(proposed_actions, indent=2)

    prompt = (
        f"USER GOAL:\n{user_goal}\n\n"
        f"KPI TARGETS:\n" + "\n".join(kpi_lines) + "\n\n"
        f"CURRENT CAMPAIGN METRICS:\n{metrics_summary}\n\n"
        f"POLICY RULES (abbreviated):\n{rag_context[:800]}\n\n"
        f"PROPOSED ACTIONS:\n{actions_summary}\n\n"
        "Score the proposal using the score_proposal tool."
    )

    try:
        response = await _client.messages.create(
            model=settings.claude_model,
            max_tokens=512,
            system=JUDGE_SYSTEM,
            tools=[_JUDGE_TOOL],
            tool_choice={"type": "tool", "name": "score_proposal"},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        return _FALLBACK

    for block in response.content:
        if block.type == "tool_use" and block.name == "score_proposal":
            try:
                return JudgeScores(**block.input)
            except Exception:
                return _FALLBACK

    return _FALLBACK

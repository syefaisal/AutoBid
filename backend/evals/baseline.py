"""
Rule-based baseline optimizer — Group A in the A/B experiment.

Implements deterministic bid/budget adjustment rules based on pacing and
CPA/ROAS thresholds.  This is the control group that the autonomous agent
(Group B) is benchmarked against.

Rules are intentionally simple so that the agent's advantage comes from
contextual reasoning and multi-lever coordination, not just threshold tuning.
"""
from __future__ import annotations

import math


def baseline_recommend(
    campaign_id: str,
    metrics: dict,
    goal: str = "",
) -> list[dict]:
    """
    Produce a list of recommended actions from deterministic rules.

    Return format mirrors ProposedAction.model_dump() minus action_id/priority
    so it can be scored by the same harness scorers as agent output.
    """
    actions: list[dict] = []

    pacing = metrics.get("pacing_rate", 1.0)
    bid = metrics.get("bid_modifier", 1.0)
    budget = metrics.get("daily_budget_usd", 1000.0)
    cpa = metrics.get("cpa_usd")
    target_cpa = metrics.get("target_cpa")
    roas = metrics.get("roas")
    target_roas = metrics.get("target_roas")
    win_rate = metrics.get("win_rate", 0.20)

    # ── Bid modifier adjustments ──────────────────────────────────────────────

    bid_delta: float = 0.0
    bid_rationale = ""

    # CPA signal (takes precedence over pacing if significant)
    if cpa and target_cpa and target_cpa > 0:
        cpa_ratio = cpa / target_cpa
        if cpa_ratio > 1.20:
            # CPA 20%+ over target → reduce bid proportionally, cap at -15%
            bid_delta = -min((cpa_ratio - 1.0) * 0.5, 0.15)
            bid_rationale = (
                f"CPA ${cpa:.2f} is {(cpa_ratio - 1)*100:.0f}% above target ${target_cpa:.2f}"
            )
        elif cpa_ratio < 0.85 and pacing < 0.95:
            # CPA well below target with room to spend more → small bid increase
            bid_delta = 0.07
            bid_rationale = (
                f"CPA ${cpa:.2f} is {(1 - cpa_ratio)*100:.0f}% below target; "
                "raising bid to capture volume"
            )

    # Pacing signal (only if CPA didn't already set a bid delta)
    if bid_delta == 0.0:
        if pacing < 0.75:
            bid_delta = 0.10
            bid_rationale = f"Severe under-pacing ({pacing:.2f}) → +10% bid"
        elif pacing < 0.85:
            bid_delta = 0.07
            bid_rationale = f"Under-pacing ({pacing:.2f}) → +7% bid"
        elif pacing > 1.20:
            bid_delta = -0.10
            bid_rationale = f"Over-pacing ({pacing:.2f}) → -10% bid"
        elif pacing > 1.10:
            bid_delta = -0.07
            bid_rationale = f"Mild over-pacing ({pacing:.2f}) → -7% bid"

    # ROAS signal for bid (separate from budget scaling below)
    if bid_delta == 0.0 and roas and target_roas and target_roas > 0:
        roas_ratio = roas / target_roas
        if roas_ratio < 0.80 and pacing > 0.80:
            bid_delta = -0.10
            bid_rationale = (
                f"ROAS {roas:.2f} is {(1 - roas_ratio)*100:.0f}% below target {target_roas:.2f}"
            )

    if bid_delta != 0.0:
        new_bid = round(max(0.50, min(2.0, bid * (1 + bid_delta))), 3)
        # Only emit if the change is meaningful (>1%)
        if abs(new_bid - bid) / bid > 0.01:
            actions.append({
                "action_type": "update_bid_modifier",
                "campaign_id": campaign_id,
                "params": {"new_bid_modifier": new_bid},
                "rationale": bid_rationale,
                "expected_impact": (
                    f"bid_modifier {bid:.3f} → {new_bid:.3f} "
                    f"({'increase' if new_bid > bid else 'decrease'} "
                    f"{abs(new_bid - bid) / bid * 100:.0f}%)"
                ),
                "confidence": 0.80,
            })

    # ── Budget scaling ────────────────────────────────────────────────────────

    budget_delta: float = 0.0
    budget_rationale = ""

    # Scale up when ROAS is strong and there is pacing headroom
    if roas and target_roas and target_roas > 0:
        roas_ratio = roas / target_roas
        if roas_ratio > 1.25 and pacing < 0.92:
            budget_delta = 0.15
            budget_rationale = (
                f"ROAS {roas:.2f} is {(roas_ratio - 1)*100:.0f}% above target "
                f"{target_roas:.2f} with pacing headroom ({pacing:.2f})"
            )
        elif roas_ratio < 0.70 and pacing > 1.05:
            # ROAS poor and overspending → cut budget modestly
            budget_delta = -0.10
            budget_rationale = (
                f"ROAS {roas:.2f} below target {target_roas:.2f} with over-pacing"
            )

    if budget_delta != 0.0:
        new_budget = round(max(1.0, budget * (1 + budget_delta)), 2)
        if abs(new_budget - budget) / budget > 0.01:
            actions.append({
                "action_type": "update_budget",
                "campaign_id": campaign_id,
                "params": {"new_daily_budget_usd": new_budget},
                "rationale": budget_rationale,
                "expected_impact": (
                    f"daily_budget ${budget:.2f} → ${new_budget:.2f} "
                    f"({budget_delta * 100:+.0f}%)"
                ),
                "confidence": 0.75,
            })

    # ── Supply source pruning ─────────────────────────────────────────────────

    if win_rate < 0.05:
        supply = metrics.get("supply_sources", [])
        # Prune the last source as a heuristic (in prod you'd have per-source stats)
        prune = supply[-1:] if supply else []
        if prune:
            actions.append({
                "action_type": "update_supply_sources",
                "campaign_id": campaign_id,
                "params": {"add_sources": [], "remove_sources": prune},
                "rationale": (
                    f"Win rate {win_rate:.1%} well below 5% floor — "
                    f"pruning {prune} as likely low-quality source"
                ),
                "expected_impact": "Improved win rate and CPA via quality filtering",
                "confidence": 0.65,
            })

    return actions


def baseline_recommend_all(campaign_metrics: dict, goal: str = "") -> list[dict]:
    """Run baseline_recommend across all campaigns in a metrics dict."""
    all_actions = []
    for cid, metrics in campaign_metrics.items():
        all_actions.extend(baseline_recommend(cid, metrics, goal))
    return all_actions

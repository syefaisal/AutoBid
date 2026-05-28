"""
Gatekeeper Node — structural pre-execution safety gate.

Position in the graph: auditor → gatekeeper → executor

Responsibilities (no LLM involved):
  1. Dry-run enforcement  — if state.dry_run is True, strip all approved
     actions into the dry_run bucket; nothing reaches the executor.
  2. Absolute hard limits — reject actions whose requested parameter change
     exceeds the per-step hard limit (guards.STEP_HARD_LIMITS), even if they
     passed the auditor.  These are system-level blocks, not approval gates.
  3. Sanity checks        — reject actions referencing campaigns that don't
     exist in campaign_metrics (stale proposal from a previous iteration).
  4. Emit structured events so the frontend can show exactly why each action
     was gated rather than silently dropped.

The gatekeeper never modifies the proposed or approved lists — it only
partitions approved_actions into the forwarded set and a new gated_actions
list that the reviewer sees in its summary.
"""
from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from agent.state import AutoBidState, ProposedAction
from agent.guards import STEP_HARD_LIMITS, _check_step_limit


async def gatekeeper_node(state: AutoBidState, config: RunnableConfig) -> dict:
    """
    Enforce dry-run mode and hard per-step limits before execution.
    Returns a filtered approved_actions list and emits gatekeeper events.
    """
    approved      = list(state.approved_actions)
    known_campaigns = set(state.campaign_metrics.keys())
    is_dry_run    = state.dry_run

    forwarded:    list[ProposedAction] = []
    gated:        list[ProposedAction] = []
    events = []

    for action in approved:
        reasons: list[str] = []

        # ── Dry-run gate ──────────────────────────────────────────────────────
        if is_dry_run:
            reasons.append("dry_run mode — execution suppressed")

        # ── Stale campaign check ──────────────────────────────────────────────
        if action.campaign_id not in known_campaigns:
            reasons.append(
                f"campaign_id '{action.campaign_id}' not in current metrics snapshot"
            )

        # ── Hard per-step change limit ────────────────────────────────────────
        # Reconstruct before/requested from params (metrics snapshot has live values)
        if action.action_type in STEP_HARD_LIMITS:
            metrics = state.campaign_metrics.get(action.campaign_id, {})
            before = {
                "bid_modifier":     metrics.get("bid_modifier", 1.0),
                "daily_budget_usd": metrics.get("daily_budget_usd", 1.0),
            }
            requested = {
                "bid_modifier":     action.params.get("new_bid_modifier",
                                        before["bid_modifier"]),
                "daily_budget_usd": action.params.get("new_daily_budget_usd",
                                        before["daily_budget_usd"]),
            }
            err = _check_step_limit(action.action_type, before, requested)
            if err:
                reasons.append(err)

        if reasons:
            gated.append(action)
            events.append({
                "type":        "action_gated",
                "action_id":   action.action_id,
                "action_type": action.action_type,
                "campaign_id": action.campaign_id,
                "dry_run":     is_dry_run,
                "reasons":     reasons,
            })
        else:
            forwarded.append(action)
            events.append({
                "type":        "action_passed_gate",
                "action_id":   action.action_id,
                "action_type": action.action_type,
                "campaign_id": action.campaign_id,
            })

    events.append({
        "type":           "gatekeeper_complete",
        "forwarded":      len(forwarded),
        "gated":          len(gated),
        "dry_run":        is_dry_run,
    })

    return {
        "approved_actions": forwarded,    # only these reach the executor
        "gated_actions":    gated,        # surfaced in review summary
        "stream_events":    events,
    }

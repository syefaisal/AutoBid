"""
Executor Node — dispatches approved actions to the tool engine.
Validates every action's params through the typed Pydantic schema before
touching any tool function — bad params are caught here, not inside tools.
Supports LangGraph interrupt() for actions still pending human approval.
"""
from pydantic import ValidationError
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from agent.state import AutoBidState, ExecutedResult, ProposedAction
from agent.schemas import parse_action_params
import agent.tools as tools


async def executor_node(state: AutoBidState, config: RunnableConfig) -> dict:
    """Execute approved actions; interrupt if human approvals are outstanding."""
    db = config["configurable"]["db"]
    trace_id = state.trace_id
    session_id = state.session_id
    is_dry_run = state.dry_run
    span_id = "executor"

    approved = list(state.approved_actions)
    pending = list(state.pending_approval_actions)

    # ── Human-in-the-loop gate ────────────────────────────────────────────────
    # Interrupt when:
    #   • the auditor flagged actions that require explicit sign-off, OR
    #   • the user enabled require_approval (all actions need review before execution)
    needs_human = pending or (state.require_approval and approved)
    if needs_human:
        all_for_human = [*pending, *approved]
        human_decision = interrupt({
            "message": f"{len(all_for_human)} action(s) ready for execution.",
            "pending_actions": [
                {
                    "action_id": a.action_id,
                    "action_type": a.action_type,
                    "campaign_id": a.campaign_id,
                    "params": a.params,
                    "rationale": a.rationale,
                }
                for a in all_for_human
            ],
        })

        approved_ids = set(human_decision.get("approved_ids", []))
        approved = [a for a in all_for_human if a.action_id in approved_ids]

    # ── Execute approved actions ──────────────────────────────────────────────
    results: list[ExecutedResult] = []
    events = []

    common = dict(
        db=db,
        session_id=session_id,
        trace_id=trace_id,
        span_id=span_id,
        rag_sources=state.rag_sources,
        is_dry_run=is_dry_run,
    )

    for action in approved:
        result = await _dispatch(action, common)
        exec_result = ExecutedResult(
            action_id=action.action_id,
            action_type=action.action_type,
            campaign_id=action.campaign_id,
            status=result.get("status", "unknown"),
            audit_id=result.get("audit_id", ""),
            result=result,
        )
        results.append(exec_result)
        events.append({
            "type": "action_executed",
            "action_id": action.action_id,
            "action_type": action.action_type,
            "campaign_id": action.campaign_id,
            "status": result.get("status"),
            "audit_id": result.get("audit_id"),
            "dry_run": is_dry_run,
        })

    return {
        "executed_results": results,
        "stream_events": events,
    }


async def _dispatch(action: ProposedAction, common: dict) -> dict:
    """Validate params via Pydantic, then route to the appropriate tool."""
    try:
        typed_params = parse_action_params(action.action_type, action.params)
    except (ValidationError, ValueError) as exc:
        return {"error": f"Param validation failed: {exc}", "status": "failed", "audit_id": ""}

    t = action.action_type
    cid = action.campaign_id
    rat = action.rationale

    if t == "update_bid_modifier":
        return await tools.update_bid_modifier(
            campaign_id=cid,
            new_bid_modifier=typed_params.new_bid_modifier,
            rationale=rat,
            **common,
        )
    if t == "update_budget":
        return await tools.update_budget(
            campaign_id=cid,
            new_daily_budget_usd=typed_params.new_daily_budget_usd,
            rationale=rat,
            **common,
        )
    if t == "pause_campaign":
        return await tools.pause_campaign(
            campaign_id=cid,
            rationale=rat,
            **common,
        )
    if t == "update_targeting":
        return await tools.update_targeting(
            campaign_id=cid,
            targeting_updates=typed_params.model_dump(exclude_none=True),
            rationale=rat,
            **common,
        )
    if t == "update_supply_sources":
        return await tools.update_supply_sources(
            campaign_id=cid,
            add_sources=typed_params.add_sources,
            remove_sources=typed_params.remove_sources,
            rationale=rat,
            **common,
        )
    if t == "route_creative":
        return await tools.route_creative(
            campaign_id=cid,
            creative_weights=typed_params.creative_weights,
            rationale=rat,
            **common,
        )

    return {"error": f"Unhandled action_type: {t!r}", "status": "failed", "audit_id": ""}

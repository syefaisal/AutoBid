"""
Analyst Node — pure data gathering, no LLM.
Fetches campaign metrics for the current plan step and runs RAG retrieval.
"""
from langchain_core.runnables import RunnableConfig

from agent.state import AutoBidState, PlanStep
from agent.tools import get_campaign_metrics
from rag.retriever import retrieve, format_context_for_prompt
from telemetry.tracing import rag_tracer


async def analyst_node(state: AutoBidState, config: RunnableConfig) -> dict:
    """Gather metrics + RAG context for the current plan step."""
    db = config["configurable"]["db"]
    trace_id = state.trace_id

    steps = state.plan_steps
    idx = state.current_step_idx
    step: PlanStep | None = steps[idx] if idx < len(steps) else None

    if step and step.campaign_ids:
        campaign_ids = step.campaign_ids
    else:
        from sqlalchemy import select
        from models.campaign import Campaign, CampaignStatus
        result = await db.execute(
            select(Campaign.id).where(Campaign.status == CampaignStatus.active)
        )
        campaign_ids = [row[0] for row in result.all()]

    metrics: dict = {}
    events = []
    for cid in campaign_ids:
        m = await get_campaign_metrics(db, cid, state.session_id, trace_id)
        if "error" not in m:
            metrics[cid] = m
            events.append({
                "type": "metrics_fetched",
                "campaign_id": cid,
                "campaign_name": m.get("name"),
                "pacing_rate": m.get("pacing_rate"),
                "cpa_usd": m.get("cpa_usd"),
                "spend_today_usd": m.get("spend_today_usd"),
                "budget_utilization_pct": m.get("budget_utilization_pct"),
            })

    rag_query = _build_rag_query(step, metrics)

    async with rag_tracer.span("rag:retrieve", trace_id=trace_id) as span:
        rag_results = retrieve(query=rag_query, n_results=6)
        span.set_attribute("query", rag_query[:100])
        span.set_attribute("results_count", len(rag_results))

    rag_ctx = format_context_for_prompt(rag_results)
    rag_sources = list({r["source"] for r in rag_results})

    events.append({
        "type": "rag_retrieved",
        "query": rag_query,
        "sources": rag_sources,
        "result_count": len(rag_results),
    })

    updated_steps = list(steps)
    if step:
        updated_steps[idx] = step.model_copy(update={"status": "in_progress"})

    return {
        "campaign_metrics": metrics,
        "rag_context": rag_ctx,
        "rag_sources": rag_sources,
        "plan_steps": updated_steps,
        "stream_events": events,
    }


def _build_rag_query(step: PlanStep | None, metrics: dict) -> str:
    parts = []
    if step:
        parts.append(step.description)
        parts.append(step.step_type)

    pacing_issues = []
    for cid, m in metrics.items():
        pr = m.get("pacing_rate", 1.0)
        if pr < 0.75:
            pacing_issues.append(f"under-pacing {pr:.2f}")
        elif pr > 1.15:
            pacing_issues.append(f"over-pacing {pr:.2f}")
        goal = m.get("optimization_goal", "")
        if goal in ("cpa", "roas"):
            parts.append(f"{goal} optimization bid adjustment")

    if pacing_issues:
        parts.append(f"pacing issues: {', '.join(pacing_issues)}")

    return " ".join(parts) if parts else "campaign optimization policy"

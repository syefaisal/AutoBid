"""
Campaign control tools.

Each tool follows:
  @tool_guard → validate → idempotency check → snapshot (Redis) → execute/dry-run
               → post-execution validation → auto-rollback on failure → audit log → return

The @tool_guard decorator (agent/guards.py) enforces:
  1. Rate limiting   (sliding window, per session)
  2. Idempotency     (return existing result if same key already completed)
  3. Hard step limit (block >20% bid change or >50% budget change in one step)

Redis snapshots (agent/redis_store.py) store pre-action campaign state so that
automatic rollback can restore exact prior state if post-execution validation fails.
"""
import uuid
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from models.campaign import Campaign
from models.audit import AuditLog, ActionStatus
from config import settings
from rag.retriever import add_campaign_memory
from agent.guards import tool_guard
from agent.redis_store import (
    write_snapshot,
    read_snapshot,
    delete_snapshot,
    validate_campaign_state,
    PostExecutionValidationError,
)

logger = logging.getLogger(__name__)


def _make_idempotency_key(campaign_id: str, action_type: str, params: dict) -> str:
    payload = f"{campaign_id}:{action_type}:{json.dumps(params, sort_keys=True)}"
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _requires_approval(action_type: str, before: dict, requested: dict) -> bool:
    """Evaluate whether an action needs human approval per policy."""
    if action_type == "pause_campaign":
        return True
    if action_type == "update_budget":
        old = before.get("daily_budget_usd", 1)
        new = requested.get("daily_budget_usd", old)
        if old > 0 and abs(new - old) / old > settings.approval_required_budget_change_pct:
            return True
    if action_type == "update_bid_modifier":
        old = before.get("bid_modifier", 1.0)
        new = requested.get("bid_modifier", old)
        if old > 0 and abs(new - old) / old > settings.approval_required_bid_change_pct:
            return True
    return False


async def _get_campaign(db: AsyncSession, campaign_id: str) -> Optional[Campaign]:
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    return result.scalar_one_or_none()


async def _write_audit(
    db: AsyncSession,
    *,
    action_type: str,
    campaign_id: str,
    session_id: str,
    trace_id: str,
    span_id: str,
    params_before: dict,
    params_requested: dict,
    params_after: Optional[dict],
    rationale: str,
    rag_sources: list,
    status: ActionStatus,
    is_dry_run: bool,
    requires_approval: bool,
    idempotency_key: str,
    latency_ms: Optional[int] = None,
    error_message: Optional[str] = None,
) -> AuditLog:
    log = AuditLog(
        id=str(uuid.uuid4()),
        idempotency_key=idempotency_key,
        trace_id=trace_id,
        span_id=span_id,
        action_type=action_type,
        campaign_id=campaign_id,
        agent_session_id=session_id,
        status=status,
        is_dry_run=is_dry_run,
        requires_approval=requires_approval,
        params_before=params_before,
        params_requested=params_requested,
        params_after=params_after,
        agent_rationale=rationale,
        rag_sources=rag_sources,
        rollback_params=params_before,
        latency_ms=latency_ms,
        error_message=error_message,
        executed_at=datetime.now(timezone.utc) if not is_dry_run else None,
        completed_at=datetime.now(timezone.utc) if status == ActionStatus.completed else None,
    )
    db.add(log)
    await db.commit()
    return log


# ─── Tool Implementations ──────────────────────────────────────────────────────

async def get_campaign_metrics(
    db: AsyncSession,
    campaign_id: str,
    session_id: str,
    trace_id: str,
) -> dict:
    """Fetch current campaign performance metrics (read-only, no audit needed)."""
    campaign = await _get_campaign(db, campaign_id)
    if not campaign:
        return {"error": f"Campaign {campaign_id} not found"}

    ctr = (campaign.clicks / campaign.impressions * 100) if campaign.impressions > 0 else 0
    cvr = (campaign.conversions / campaign.clicks * 100) if campaign.clicks > 0 else 0
    cpa = (campaign.spend_today_usd / campaign.conversions) if campaign.conversions > 0 else None
    roas = (campaign.revenue_usd / campaign.spend_total_usd) if campaign.spend_total_usd > 0 else None
    budget_utilization = (campaign.spend_today_usd / campaign.daily_budget_usd * 100) if campaign.daily_budget_usd > 0 else 0

    return {
        "campaign_id": campaign_id,
        "name": campaign.name,
        "status": campaign.status,
        "optimization_goal": campaign.optimization_goal,
        "daily_budget_usd": campaign.daily_budget_usd,
        "spend_today_usd": round(campaign.spend_today_usd, 2),
        "spend_total_usd": round(campaign.spend_total_usd, 2),
        "budget_utilization_pct": round(budget_utilization, 1),
        "base_bid_cpm": campaign.base_bid_cpm,
        "bid_modifier": campaign.bid_modifier,
        "effective_bid_cpm": round(campaign.base_bid_cpm * campaign.bid_modifier, 2),
        "pacing_rate": round(campaign.pacing_rate, 3),
        "impressions": campaign.impressions,
        "clicks": campaign.clicks,
        "conversions": campaign.conversions,
        "ctr_pct": round(ctr, 3),
        "cvr_pct": round(cvr, 3),
        "cpa_usd": round(cpa, 2) if cpa else None,
        "roas": round(roas, 2) if roas else None,
        "target_cpa": campaign.target_cpa,
        "target_roas": campaign.target_roas,
        "targeting": campaign.targeting,
        "supply_sources": campaign.supply_sources,
        "pacing_type": campaign.pacing_type,
    }


@tool_guard("update_bid_modifier")
async def update_bid_modifier(
    db: AsyncSession,
    campaign_id: str,
    new_bid_modifier: float,
    rationale: str,
    session_id: str,
    trace_id: str,
    span_id: str,
    rag_sources: list,
    is_dry_run: bool = False,
) -> dict:
    """Adjust global bid modifier for a campaign. Clamped to [0.50, 2.00]."""
    import time
    t0 = time.time()
    campaign = await _get_campaign(db, campaign_id)
    if not campaign:
        return {"error": f"Campaign {campaign_id} not found"}

    new_modifier = max(0.50, min(2.00, round(new_bid_modifier, 3)))
    params_before = {"bid_modifier": campaign.bid_modifier, "base_bid_cpm": campaign.base_bid_cpm}
    params_requested = {"bid_modifier": new_modifier}

    ikey = _make_idempotency_key(campaign_id, "update_bid_modifier", params_requested)
    needs_approval = _requires_approval("update_bid_modifier", params_before, params_requested)

    change_pct = (new_modifier - campaign.bid_modifier) / campaign.bid_modifier * 100

    audit_id = str(uuid.uuid4())
    params_after = None
    auto_rolled_back = False

    if is_dry_run:
        status = ActionStatus.dry_run
    elif needs_approval:
        status = ActionStatus.pending_approval
    else:
        # Write pre-action snapshot to Redis before mutating
        snapshot = {**params_before, "status": str(campaign.status),
                    "daily_budget_usd": campaign.daily_budget_usd}
        await write_snapshot(audit_id, snapshot)

        await db.execute(
            update(Campaign).where(Campaign.id == campaign_id).values(bid_modifier=new_modifier)
        )
        await db.commit()
        params_after = {"bid_modifier": new_modifier}
        status = ActionStatus.completed

        # Post-execution validation — auto-rollback if result is out-of-bounds
        post_state = {**snapshot, "bid_modifier": new_modifier}
        try:
            validate_campaign_state(post_state)
            await delete_snapshot(audit_id)
        except PostExecutionValidationError as exc:
            logger.error("Auto-rollback triggered for %s: %s", audit_id, exc)
            snap = await read_snapshot(audit_id)
            if snap:
                await db.execute(
                    update(Campaign).where(Campaign.id == campaign_id)
                    .values(bid_modifier=snap["bid_modifier"])
                )
                await db.commit()
            await delete_snapshot(audit_id)
            params_after = None
            status = ActionStatus.rolled_back
            auto_rolled_back = True

        if not auto_rolled_back:
            add_campaign_memory(
                campaign_id, "bid_modifier_change",
                f"Bid modifier changed from {params_before['bid_modifier']:.2f} to {new_modifier:.2f} ({change_pct:+.1f}%). Reason: {rationale}",
                {"action_type": "update_bid_modifier",
                 "old_value": str(params_before["bid_modifier"]),
                 "new_value": str(new_modifier)},
            )

    audit = await _write_audit(
        db,
        action_type="update_bid_modifier",
        campaign_id=campaign_id,
        session_id=session_id,
        trace_id=trace_id,
        span_id=span_id,
        params_before=params_before,
        params_requested=params_requested,
        params_after=params_after,
        rationale=rationale,
        rag_sources=rag_sources,
        status=status,
        is_dry_run=is_dry_run,
        requires_approval=needs_approval,
        idempotency_key=ikey,
        latency_ms=int((time.time() - t0) * 1000),
    )

    return {
        "action":           "update_bid_modifier",
        "audit_id":         audit.id,
        "campaign_id":      campaign_id,
        "status":           status,
        "dry_run":          is_dry_run,
        "requires_approval": needs_approval,
        "auto_rolled_back": auto_rolled_back,
        "before":           params_before,
        "requested":        params_requested,
        "applied":          params_after,
        "change_pct":       round(change_pct, 1),
        "effective_bid_cpm": round(campaign.base_bid_cpm * new_modifier, 2),
    }


@tool_guard("update_budget")
async def update_budget(
    db: AsyncSession,
    campaign_id: str,
    new_daily_budget_usd: float,
    rationale: str,
    session_id: str,
    trace_id: str,
    span_id: str,
    rag_sources: list,
    is_dry_run: bool = False,
) -> dict:
    """Adjust daily budget. >25% change triggers approval gate."""
    import time
    t0 = time.time()
    campaign = await _get_campaign(db, campaign_id)
    if not campaign:
        return {"error": f"Campaign {campaign_id} not found"}

    new_budget = max(1.0, round(new_daily_budget_usd, 2))
    params_before = {"daily_budget_usd": campaign.daily_budget_usd}
    params_requested = {"daily_budget_usd": new_budget}

    ikey = _make_idempotency_key(campaign_id, "update_budget", params_requested)
    needs_approval = _requires_approval("update_budget", params_before, params_requested)
    change_pct = (new_budget - campaign.daily_budget_usd) / campaign.daily_budget_usd * 100

    audit_id = str(uuid.uuid4())
    params_after = None
    auto_rolled_back = False

    if is_dry_run:
        status = ActionStatus.dry_run
    elif needs_approval:
        status = ActionStatus.pending_approval
    else:
        snapshot = {"daily_budget_usd": campaign.daily_budget_usd,
                    "bid_modifier": campaign.bid_modifier,
                    "status": str(campaign.status)}
        await write_snapshot(audit_id, snapshot)

        await db.execute(
            update(Campaign).where(Campaign.id == campaign_id).values(daily_budget_usd=new_budget)
        )
        await db.commit()
        params_after = {"daily_budget_usd": new_budget}
        status = ActionStatus.completed

        post_state = {**snapshot, "daily_budget_usd": new_budget}
        try:
            validate_campaign_state(post_state)
            await delete_snapshot(audit_id)
        except PostExecutionValidationError as exc:
            logger.error("Auto-rollback triggered for budget update %s: %s", audit_id, exc)
            snap = await read_snapshot(audit_id)
            if snap:
                await db.execute(
                    update(Campaign).where(Campaign.id == campaign_id)
                    .values(daily_budget_usd=snap["daily_budget_usd"])
                )
                await db.commit()
            await delete_snapshot(audit_id)
            params_after = None
            status = ActionStatus.rolled_back
            auto_rolled_back = True

    audit = await _write_audit(
        db,
        action_type="update_budget",
        campaign_id=campaign_id,
        session_id=session_id,
        trace_id=trace_id,
        span_id=span_id,
        params_before=params_before,
        params_requested=params_requested,
        params_after=params_after,
        rationale=rationale,
        rag_sources=rag_sources,
        status=status,
        is_dry_run=is_dry_run,
        requires_approval=needs_approval,
        idempotency_key=ikey,
        latency_ms=int((time.time() - t0) * 1000),
    )

    return {
        "action":           "update_budget",
        "audit_id":         audit.id,
        "campaign_id":      campaign_id,
        "status":           status,
        "dry_run":          is_dry_run,
        "requires_approval": needs_approval,
        "auto_rolled_back": auto_rolled_back,
        "before":           params_before,
        "requested":        params_requested,
        "applied":          params_after,
        "change_pct":       round(change_pct, 1),
    }


@tool_guard("pause_campaign")
async def pause_campaign(
    db: AsyncSession,
    campaign_id: str,
    rationale: str,
    session_id: str,
    trace_id: str,
    span_id: str,
    rag_sources: list,
    is_dry_run: bool = False,
) -> dict:
    """Pause an active campaign. Always requires human approval."""
    import time
    t0 = time.time()
    campaign = await _get_campaign(db, campaign_id)
    if not campaign:
        return {"error": f"Campaign {campaign_id} not found"}

    params_before = {"status": campaign.status}
    params_requested = {"status": "paused"}
    ikey = _make_idempotency_key(campaign_id, "pause_campaign", {})

    if is_dry_run:
        status = ActionStatus.dry_run
        params_after = None
    else:
        # Pause always requires approval
        status = ActionStatus.pending_approval
        params_after = None

    audit = await _write_audit(
        db,
        action_type="pause_campaign",
        campaign_id=campaign_id,
        session_id=session_id,
        trace_id=trace_id,
        span_id=span_id,
        params_before=params_before,
        params_requested=params_requested,
        params_after=params_after,
        rationale=rationale,
        rag_sources=rag_sources,
        status=status,
        is_dry_run=is_dry_run,
        requires_approval=True,
        idempotency_key=ikey,
        latency_ms=int((time.time() - t0) * 1000),
    )

    return {
        "action": "pause_campaign",
        "audit_id": audit.id,
        "campaign_id": campaign_id,
        "status": status,
        "dry_run": is_dry_run,
        "requires_approval": True,
        "message": "Pause request queued for human approval. Campaign remains active until approved.",
    }


@tool_guard("update_targeting")
async def update_targeting(
    db: AsyncSession,
    campaign_id: str,
    targeting_updates: dict,
    rationale: str,
    session_id: str,
    trace_id: str,
    span_id: str,
    rag_sources: list,
    is_dry_run: bool = False,
) -> dict:
    """Update targeting constraints (geo, device, audience, daypart)."""
    import time
    t0 = time.time()
    campaign = await _get_campaign(db, campaign_id)
    if not campaign:
        return {"error": f"Campaign {campaign_id} not found"}

    current_targeting = campaign.targeting or {}
    merged = {**current_targeting, **targeting_updates}
    params_before = {"targeting": current_targeting}
    params_requested = {"targeting": targeting_updates}
    ikey = _make_idempotency_key(campaign_id, "update_targeting", targeting_updates)

    if is_dry_run:
        status = ActionStatus.dry_run
        params_after = None
    else:
        await db.execute(
            update(Campaign).where(Campaign.id == campaign_id).values(targeting=merged)
        )
        await db.commit()
        params_after = {"targeting": merged}
        status = ActionStatus.completed

        add_campaign_memory(
            campaign_id, "targeting_change",
            f"Targeting updated: {json.dumps(targeting_updates)}. Reason: {rationale}",
        )

    audit = await _write_audit(
        db,
        action_type="update_targeting",
        campaign_id=campaign_id,
        session_id=session_id,
        trace_id=trace_id,
        span_id=span_id,
        params_before=params_before,
        params_requested=params_requested,
        params_after=params_after,
        rationale=rationale,
        rag_sources=rag_sources,
        status=status,
        is_dry_run=is_dry_run,
        requires_approval=False,
        idempotency_key=ikey,
        latency_ms=int((time.time() - t0) * 1000),
    )

    return {
        "action": "update_targeting",
        "audit_id": audit.id,
        "campaign_id": campaign_id,
        "status": status,
        "dry_run": is_dry_run,
        "before": params_before,
        "requested": params_requested,
        "applied": params_after,
    }


@tool_guard("update_supply_sources")
async def update_supply_sources(
    db: AsyncSession,
    campaign_id: str,
    add_sources: list[str],
    remove_sources: list[str],
    rationale: str,
    session_id: str,
    trace_id: str,
    span_id: str,
    rag_sources: list,
    is_dry_run: bool = False,
) -> dict:
    """Modify the allowlist of supply sources (SSPs/exchanges)."""
    import time
    t0 = time.time()
    campaign = await _get_campaign(db, campaign_id)
    if not campaign:
        return {"error": f"Campaign {campaign_id} not found"}

    current = set(campaign.supply_sources or [])
    new_sources = list((current | set(add_sources)) - set(remove_sources))
    params_before = {"supply_sources": campaign.supply_sources}
    params_requested = {"add": add_sources, "remove": remove_sources}
    ikey = _make_idempotency_key(campaign_id, "update_supply", {"add": sorted(add_sources), "remove": sorted(remove_sources)})

    if is_dry_run:
        status = ActionStatus.dry_run
        params_after = None
    else:
        await db.execute(
            update(Campaign).where(Campaign.id == campaign_id).values(supply_sources=new_sources)
        )
        await db.commit()
        params_after = {"supply_sources": new_sources}
        status = ActionStatus.completed

    audit = await _write_audit(
        db,
        action_type="update_supply_sources",
        campaign_id=campaign_id,
        session_id=session_id,
        trace_id=trace_id,
        span_id=span_id,
        params_before=params_before,
        params_requested=params_requested,
        params_after=params_after,
        rationale=rationale,
        rag_sources=rag_sources,
        status=status,
        is_dry_run=is_dry_run,
        requires_approval=False,
        idempotency_key=ikey,
        latency_ms=int((time.time() - t0) * 1000),
    )

    return {
        "action": "update_supply_sources",
        "audit_id": audit.id,
        "campaign_id": campaign_id,
        "status": status,
        "dry_run": is_dry_run,
        "before": params_before,
        "applied": params_after,
    }


@tool_guard("route_creative")
async def route_creative(
    db: AsyncSession,
    campaign_id: str,
    creative_weights: dict,
    rationale: str,
    session_id: str,
    trace_id: str,
    span_id: str,
    rag_sources: list,
    is_dry_run: bool = False,
) -> dict:
    """Set traffic weighting for creatives (creative routing/rotation)."""
    import time
    t0 = time.time()
    campaign = await _get_campaign(db, campaign_id)
    if not campaign:
        return {"error": f"Campaign {campaign_id} not found"}

    params_before = {"creative_ids": campaign.creative_ids}
    params_requested = {"creative_weights": creative_weights}
    ikey = _make_idempotency_key(campaign_id, "route_creative", creative_weights)

    targeting_update = campaign.targeting or {}
    targeting_update["creative_weights"] = creative_weights

    if is_dry_run:
        status = ActionStatus.dry_run
        params_after = None
    else:
        await db.execute(
            update(Campaign).where(Campaign.id == campaign_id).values(targeting=targeting_update)
        )
        await db.commit()
        params_after = {"creative_weights": creative_weights}
        status = ActionStatus.completed

    audit = await _write_audit(
        db,
        action_type="route_creative",
        campaign_id=campaign_id,
        session_id=session_id,
        trace_id=trace_id,
        span_id=span_id,
        params_before=params_before,
        params_requested=params_requested,
        params_after=params_after,
        rationale=rationale,
        rag_sources=rag_sources,
        status=status,
        is_dry_run=is_dry_run,
        requires_approval=False,
        idempotency_key=ikey,
        latency_ms=int((time.time() - t0) * 1000),
    )

    return {
        "action": "route_creative",
        "audit_id": audit.id,
        "campaign_id": campaign_id,
        "status": status,
        "dry_run": is_dry_run,
        "creative_weights": creative_weights,
    }


async def rollback_action(
    db: AsyncSession,
    audit_id: str,
    session_id: str,
    trace_id: str,
) -> dict:
    """Rollback a previously executed action using its pre-action snapshot."""
    from sqlalchemy import select
    result = await db.execute(select(AuditLog).where(AuditLog.id == audit_id))
    log = result.scalar_one_or_none()
    if not log:
        return {"error": f"Audit log {audit_id} not found"}
    if log.status != ActionStatus.completed:
        return {"error": f"Action {audit_id} is not in completed state (status={log.status})"}

    rollback_params = log.rollback_params
    campaign = await _get_campaign(db, log.campaign_id)
    if not campaign:
        return {"error": "Campaign not found"}

    allowed_keys = {"bid_modifier", "daily_budget_usd", "status", "targeting", "supply_sources"}
    safe_rollback = {k: v for k, v in rollback_params.items() if k in allowed_keys}

    await db.execute(
        update(Campaign).where(Campaign.id == log.campaign_id).values(**safe_rollback)
    )
    await db.execute(
        update(AuditLog).where(AuditLog.id == audit_id).values(
            status=ActionStatus.rolled_back,
            rolled_back_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()

    return {
        "action": "rollback",
        "audit_id": audit_id,
        "campaign_id": log.campaign_id,
        "rolled_back_to": safe_rollback,
        "status": "rolled_back",
    }


async def approve_action(
    db: AsyncSession,
    audit_id: str,
    approved_by: str,
) -> dict:
    """Approve a pending action and execute it."""
    from sqlalchemy import select
    result = await db.execute(select(AuditLog).where(AuditLog.id == audit_id))
    log = result.scalar_one_or_none()
    if not log:
        return {"error": "Audit log not found"}
    if log.status != ActionStatus.pending_approval:
        return {"error": f"Action is not pending approval (status={log.status})"}

    campaign = await _get_campaign(db, log.campaign_id)
    if not campaign:
        return {"error": "Campaign not found"}

    # Execute the action
    safe_params = {k: v for k, v in log.params_requested.items()
                   if k in {"bid_modifier", "daily_budget_usd", "status", "targeting", "supply_sources"}}
    if safe_params:
        await db.execute(update(Campaign).where(Campaign.id == log.campaign_id).values(**safe_params))

    await db.execute(
        update(AuditLog).where(AuditLog.id == audit_id).values(
            status=ActionStatus.completed,
            approved_by=approved_by,
            params_after=log.params_requested,
            executed_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()

    return {"action": "approve", "audit_id": audit_id, "status": "completed", "approved_by": approved_by}


# ── Telemetry query tool ──────────────────────────────────────────────────────

async def query_telemetry_aggregates(
    db: AsyncSession,
    metric: str,
    period: str = "24h",
    campaign_id: Optional[str] = None,
) -> dict:
    """
    Pre-built telemetry query tool for agents.

    Agents call this to get structured aggregate performance data (exact
    numbers from SQL) instead of searching for it through RAG over text.
    Returns the same payload as GET /telemetry/aggregate.

    Supported metrics: cpa, roas, ctr, pacing_rate, spend,
                       impressions, clicks, conversions, win_rate
    Supported periods: 1h, 6h, 24h, 7d, 30d
    """
    from sqlalchemy import func
    from models.campaign import CampaignSnapshot, Campaign as CampaignModel

    _valid_metrics = {"cpa", "roas", "ctr", "pacing_rate", "spend",
                      "impressions", "clicks", "conversions", "win_rate"}
    _valid_periods = {"1h": 1, "6h": 6, "24h": 24, "7d": 168, "30d": 720}

    if metric not in _valid_metrics:
        return {"error": f"metric must be one of {sorted(_valid_metrics)}"}
    if period not in _valid_periods:
        return {"error": f"period must be one of {sorted(_valid_periods.keys())}"}

    hours = _valid_periods[period]

    stmt = (
        select(
            CampaignSnapshot.campaign_id,
            func.sum(CampaignSnapshot.impressions).label("impr"),
            func.sum(CampaignSnapshot.clicks).label("clicks"),
            func.sum(CampaignSnapshot.conversions).label("convs"),
            func.sum(CampaignSnapshot.spend_usd).label("spend"),
            func.sum(CampaignSnapshot.revenue_usd).label("rev"),
            func.avg(CampaignSnapshot.win_rate).label("avg_win_rate"),
            func.count(CampaignSnapshot.id).label("data_points"),
        )
        .where(
            func.datetime(CampaignSnapshot.hour_ts)
            >= func.datetime("now", f"-{hours} hours")
        )
    )
    if campaign_id:
        stmt = stmt.where(CampaignSnapshot.campaign_id == campaign_id)
    stmt = stmt.group_by(CampaignSnapshot.campaign_id)

    result = await db.execute(stmt)
    rows = result.mappings().all()

    # Pull pacing_rate from live campaign table
    camp_result = await db.execute(select(CampaignModel))
    pacing = {c.id: c.pacing_rate for c in camp_result.scalars().all()}

    output = []
    for row in rows:
        impr  = row["impr"] or 0
        clk   = row["clicks"] or 0
        convs = row["convs"] or 0
        spend = float(row["spend"] or 0)
        rev   = float(row["rev"] or 0)
        cid   = row["campaign_id"]

        output.append({
            "campaign_id":   cid,
            "period":        period,
            "data_points":   row["data_points"],
            "impressions":   impr,
            "clicks":        clk,
            "conversions":   convs,
            "spend_usd":     round(spend, 2),
            "cpa":           round(spend / convs, 2) if convs > 0 else None,
            "roas":          round(rev / spend, 3) if spend > 0 else None,
            "ctr":           round(clk / impr * 100, 3) if impr > 0 else None,
            "pacing_rate":   round(pacing.get(cid, 1.0), 3),
            "avg_win_rate":  round(float(row["avg_win_rate"] or 0), 3),
        })

    return {
        "metric":    metric,
        "period":    period,
        "campaigns": output,
    }

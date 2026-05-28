"""
Real-time Telemetry API — aggregate performance metrics exposed as structured
JSON endpoints.

Agents query these endpoints via the `query_telemetry_aggregates` tool in
agent/tools.py rather than attempting to retrieve raw logs through RAG.
This separates:
  - Unstructured knowledge (policies, playbooks) → RAG retrieval
  - Structured time-series data (CPA, pacing, spend) → SQL aggregation here
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_db
from models.campaign import Campaign, CampaignSnapshot

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

# ── Helpers ───────────────────────────────────────────────────────────────────

_VALID_METRICS = {
    "cpa", "roas", "ctr", "pacing_rate", "spend",
    "impressions", "clicks", "conversions", "win_rate",
}

_VALID_PERIODS = {"1h", "6h", "24h", "7d", "30d"}

_PERIOD_HOURS: dict[str, int] = {
    "1h": 1, "6h": 6, "24h": 24, "7d": 168, "30d": 720,
}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/aggregate")
async def aggregate_metrics(
    metric: str = Query("cpa", description=f"One of: {', '.join(sorted(_VALID_METRICS))}"),
    period: str = Query("24h", description=f"One of: {', '.join(sorted(_VALID_PERIODS))}"),
    campaign_id: str | None = Query(None, description="Filter to a single campaign"),
    db: AsyncSession = Depends(get_db),
):
    """
    Return aggregate performance statistics for one metric over a time window.

    Agents call this to get exact numbers (e.g. average CPA over last 24h)
    instead of searching for it in unstructured telemetry text via RAG.

    Example: GET /telemetry/aggregate?metric=cpa&period=24h&campaign_id=camp_001
    """
    if metric not in _VALID_METRICS:
        raise HTTPException(400, f"metric must be one of: {sorted(_VALID_METRICS)}")
    if period not in _VALID_PERIODS:
        raise HTTPException(400, f"period must be one of: {sorted(_VALID_PERIODS)}")

    hours = _PERIOD_HOURS[period]

    stmt = (
        select(
            CampaignSnapshot.campaign_id,
            func.sum(CampaignSnapshot.impressions).label("total_impressions"),
            func.sum(CampaignSnapshot.clicks).label("total_clicks"),
            func.sum(CampaignSnapshot.conversions).label("total_conversions"),
            func.sum(CampaignSnapshot.spend_usd).label("total_spend"),
            func.sum(CampaignSnapshot.revenue_usd).label("total_revenue"),
            func.avg(CampaignSnapshot.win_rate).label("avg_win_rate"),
            func.avg(CampaignSnapshot.fill_rate).label("avg_fill_rate"),
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

    output = []
    for row in rows:
        impr   = row["total_impressions"] or 0
        clicks = row["total_clicks"] or 0
        convs  = row["total_conversions"] or 0
        spend  = row["total_spend"] or 0.0
        rev    = row["total_revenue"] or 0.0

        computed = {
            "campaign_id":   row["campaign_id"],
            "period":        period,
            "data_points":   row["data_points"],
            "impressions":   impr,
            "clicks":        clicks,
            "conversions":   convs,
            "spend_usd":     round(spend, 2),
            "revenue_usd":   round(rev, 2),
            "ctr":           round(clicks / impr * 100, 3) if impr > 0 else None,
            "cpa":           round(spend / convs, 2) if convs > 0 else None,
            "roas":          round(rev / spend, 3) if spend > 0 else None,
            "avg_win_rate":  round(row["avg_win_rate"] or 0, 3),
            "avg_fill_rate": round(row["avg_fill_rate"] or 0, 3),
        }
        output.append(computed)

    return {
        "metric":    metric,
        "period":    period,
        "campaigns": output,
    }


@router.get("/compare")
async def compare_campaigns(
    metric: str = Query("cpa", description="Metric to compare across campaigns"),
    period: str = Query("24h"),
    db: AsyncSession = Depends(get_db),
):
    """
    Cross-campaign comparison for a single metric.
    Returns a sorted leaderboard with deviation from fleet average.

    Useful for agents to identify outliers (e.g. worst-pacing campaigns)
    without fetching every campaign's metrics individually.
    """
    if metric not in _VALID_METRICS:
        raise HTTPException(400, f"metric must be one of: {sorted(_VALID_METRICS)}")
    if period not in _VALID_PERIODS:
        raise HTTPException(400, f"period must be one of: {sorted(_VALID_PERIODS)}")

    hours = _PERIOD_HOURS[period]

    snap_stmt = (
        select(
            CampaignSnapshot.campaign_id,
            func.sum(CampaignSnapshot.impressions).label("impr"),
            func.sum(CampaignSnapshot.clicks).label("clicks"),
            func.sum(CampaignSnapshot.conversions).label("convs"),
            func.sum(CampaignSnapshot.spend_usd).label("spend"),
            func.sum(CampaignSnapshot.revenue_usd).label("rev"),
        )
        .where(
            func.datetime(CampaignSnapshot.hour_ts)
            >= func.datetime("now", f"-{hours} hours")
        )
        .group_by(CampaignSnapshot.campaign_id)
    )

    snap_result = await db.execute(snap_stmt)
    snap_rows = {row.campaign_id: row for row in snap_result}

    # Pull current campaign state for pacing_rate
    camp_result = await db.execute(select(Campaign))
    campaigns = {c.id: c for c in camp_result.scalars().all()}

    rows_out = []
    for cid, c in campaigns.items():
        snap = snap_rows.get(cid)
        impr  = snap.impr if snap else 0
        clk   = snap.clicks if snap else 0
        convs = snap.convs if snap else 0
        spend = float(snap.spend) if snap else 0.0
        rev   = float(snap.rev) if snap else 0.0

        metric_value: float | None = None
        if metric == "cpa":
            metric_value = round(spend / convs, 2) if convs > 0 else None
        elif metric == "roas":
            metric_value = round(rev / spend, 3) if spend > 0 else None
        elif metric == "ctr":
            metric_value = round(clk / impr * 100, 3) if impr > 0 else None
        elif metric == "pacing_rate":
            metric_value = round(c.pacing_rate, 3)
        elif metric == "spend":
            metric_value = round(spend, 2)
        elif metric == "impressions":
            metric_value = impr
        elif metric == "clicks":
            metric_value = clk
        elif metric == "conversions":
            metric_value = convs

        rows_out.append({
            "campaign_id":   cid,
            "campaign_name": c.name,
            "status":        c.status,
            "metric_value":  metric_value,
        })

    # Remove nulls for averaging, compute fleet stats
    values = [r["metric_value"] for r in rows_out if r["metric_value"] is not None]
    fleet_avg = round(sum(values) / len(values), 3) if values else None

    for r in rows_out:
        if r["metric_value"] is not None and fleet_avg is not None:
            r["pct_vs_fleet"] = round((r["metric_value"] - fleet_avg) / fleet_avg * 100, 1)
        else:
            r["pct_vs_fleet"] = None

    # Sort: nulls last, then by metric value ascending (worst performers first for CPA/pacing)
    rows_out.sort(key=lambda x: (x["metric_value"] is None, x["metric_value"] or 0))

    return {
        "metric":      metric,
        "period":      period,
        "fleet_avg":   fleet_avg,
        "campaigns":   rows_out,
    }


@router.get("/timeseries/{campaign_id}")
async def timeseries(
    campaign_id: str,
    hours: int = Query(24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
):
    """
    Hourly time-series for a single campaign.
    Returns raw snapshot rows — useful for trend detection.
    """
    result = await db.execute(
        select(CampaignSnapshot)
        .where(CampaignSnapshot.campaign_id == campaign_id)
        .order_by(CampaignSnapshot.hour_ts.desc())
        .limit(hours)
    )
    snaps = result.scalars().all()
    if not snaps:
        raise HTTPException(404, f"No telemetry for campaign {campaign_id}")

    return {
        "campaign_id": campaign_id,
        "hours":       hours,
        "rows": [
            {
                "hour_ts":     s.hour_ts.isoformat(),
                "impressions": s.impressions,
                "clicks":      s.clicks,
                "conversions": s.conversions,
                "spend_usd":   s.spend_usd,
                "revenue_usd": s.revenue_usd,
                "avg_bid_cpm": s.avg_bid_cpm,
                "win_rate":    s.win_rate,
                "fill_rate":   s.fill_rate,
                "cpa":         round(s.spend_usd / s.conversions, 2) if s.conversions else None,
                "roas":        round(s.revenue_usd / s.spend_usd, 3) if s.spend_usd else None,
                "ctr":         round(s.clicks / s.impressions * 100, 3) if s.impressions else None,
            }
            for s in reversed(snaps)
        ],
    }

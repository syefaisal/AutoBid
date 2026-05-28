from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from models import Campaign, CampaignSnapshot, get_db
from agent.tools import get_campaign_metrics

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("/")
async def list_campaigns(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign).order_by(Campaign.created_at))
    campaigns = result.scalars().all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "advertiser": c.advertiser,
            "status": c.status,
            "optimization_goal": c.optimization_goal,
            "daily_budget_usd": c.daily_budget_usd,
            "spend_today_usd": c.spend_today_usd,
            "pacing_rate": c.pacing_rate,
            "bid_modifier": c.bid_modifier,
            "base_bid_cpm": c.base_bid_cpm,
            "impressions": c.impressions,
            "clicks": c.clicks,
            "conversions": c.conversions,
            "ctr_pct": round(c.clicks / c.impressions * 100, 3) if c.impressions > 0 else 0,
            "cpa_usd": round(c.spend_today_usd / c.conversions, 2) if c.conversions > 0 else None,
            "roas": round(c.revenue_usd / c.spend_total_usd, 2) if c.spend_total_usd > 0 else None,
        }
        for c in campaigns
    ]


@router.get("/{campaign_id}/metrics")
async def get_metrics(campaign_id: str, db: AsyncSession = Depends(get_db)):
    metrics = await get_campaign_metrics(db, campaign_id, "api", "api")
    if "error" in metrics:
        raise HTTPException(status_code=404, detail=metrics["error"])
    return metrics


@router.get("/{campaign_id}/history")
async def get_history(campaign_id: str, hours: int = 24, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CampaignSnapshot)
        .where(CampaignSnapshot.campaign_id == campaign_id)
        .order_by(desc(CampaignSnapshot.hour_ts))
        .limit(hours)
    )
    snaps = result.scalars().all()
    return [
        {
            "hour_ts": s.hour_ts.isoformat(),
            "impressions": s.impressions,
            "clicks": s.clicks,
            "conversions": s.conversions,
            "spend_usd": s.spend_usd,
            "revenue_usd": s.revenue_usd,
            "avg_bid_cpm": s.avg_bid_cpm,
            "win_rate": s.win_rate,
            "fill_rate": s.fill_rate,
        }
        for s in reversed(snaps)
    ]

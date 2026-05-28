"""Seed realistic campaign data for demo purposes."""
import uuid
import random
from datetime import datetime, timedelta, timezone
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from models.campaign import Campaign, CampaignSnapshot, CampaignStatus, OptimizationGoal
from models.audit import Experiment
from rag.retriever import add_campaign_memory, add_telemetry_aggregate

ADVERTISERS = [
    ("Nike", "Footwear"),
    ("Netflix", "Entertainment"),
    ("Chase", "Financial Services"),
    ("Whole Foods", "Grocery"),
    ("Toyota", "Automotive"),
]

SUPPLY_SOURCES_TIER1 = ["google_adx", "magnite", "pubmatic", "index_exchange", "openx"]
SUPPLY_SOURCES_TIER2 = ["xandr", "sovrn", "sharethrough"]

SAMPLE_CAMPAIGNS = [
    {
        "name": "Nike Air Max — Retargeting Q2",
        "advertiser": "Nike",
        "goal": OptimizationGoal.cpa,
        "daily_budget": 15000,
        "total_budget": 450000,
        "base_bid": 4.20,
        "target_cpa": 28.0,
        "pacing_rate": 0.72,  # under-pacing
        "bid_modifier": 0.95,
        "spend_pct": 0.68,
        "status": CampaignStatus.active,
        "issue": "under_delivery",
    },
    {
        "name": "Netflix Summer Originals — Prospecting",
        "advertiser": "Netflix",
        "goal": OptimizationGoal.ctr,
        "daily_budget": 22000,
        "total_budget": 660000,
        "base_bid": 6.80,
        "target_cpa": None,
        "target_ctr": 0.8,
        "pacing_rate": 1.18,  # over-pacing
        "bid_modifier": 1.10,
        "spend_pct": 1.20,
        "status": CampaignStatus.active,
        "issue": "over_pacing",
    },
    {
        "name": "Chase Sapphire — CPA Optimization",
        "advertiser": "Chase",
        "goal": OptimizationGoal.cpa,
        "daily_budget": 35000,
        "total_budget": 1050000,
        "base_bid": 8.50,
        "target_cpa": 45.0,
        "pacing_rate": 1.02,
        "bid_modifier": 1.0,
        "spend_pct": 1.0,
        "status": CampaignStatus.active,
        "issue": None,
    },
    {
        "name": "Whole Foods — Weekly Promotions",
        "advertiser": "Whole Foods",
        "goal": OptimizationGoal.roas,
        "daily_budget": 8500,
        "total_budget": 170000,
        "base_bid": 3.10,
        "target_roas": 4.2,
        "pacing_rate": 0.58,  # severely under-pacing
        "bid_modifier": 0.88,
        "spend_pct": 0.55,
        "status": CampaignStatus.active,
        "issue": "severe_under_delivery",
    },
    {
        "name": "Toyota RAV4 — Brand Awareness CTV",
        "advertiser": "Toyota",
        "goal": OptimizationGoal.reach,
        "daily_budget": 28000,
        "total_budget": 840000,
        "base_bid": 12.00,
        "target_cpa": None,
        "pacing_rate": 0.97,
        "bid_modifier": 1.05,
        "spend_pct": 0.97,
        "status": CampaignStatus.active,
        "issue": None,
    },
    {
        "name": "Nike Running — Paused (Creative Review)",
        "advertiser": "Nike",
        "goal": OptimizationGoal.ctr,
        "daily_budget": 5000,
        "total_budget": 75000,
        "base_bid": 2.80,
        "target_cpa": None,
        "pacing_rate": 0.0,
        "bid_modifier": 1.0,
        "spend_pct": 0.0,
        "status": CampaignStatus.paused,
        "issue": None,
    },
]


def _make_metrics(spend_pct: float, goal: OptimizationGoal, daily_budget: float, target_cpa: float = None):
    """Generate realistic performance metrics."""
    spend = daily_budget * spend_pct
    cpm = random.uniform(3.5, 9.0)
    impressions = int(spend / cpm * 1000)
    ctr = random.uniform(0.003, 0.015)
    clicks = int(impressions * ctr)
    cvr = random.uniform(0.02, 0.08)
    conversions = int(clicks * cvr)
    revenue = conversions * random.uniform(50, 200)
    return impressions, clicks, conversions, spend, revenue


async def seed_campaigns(db: AsyncSession):
    from sqlalchemy import select
    result = await db.execute(select(Campaign).limit(1))
    if result.scalar_one_or_none():
        return  # Already seeded

    campaign_ids = []
    for cfg in SAMPLE_CAMPAIGNS:
        cid = f"cmp_{uuid.uuid4().hex[:8]}"
        campaign_ids.append(cid)
        imps, clicks, convs, spend, revenue = _make_metrics(
            cfg["spend_pct"], cfg["goal"], cfg["daily_budget"], cfg.get("target_cpa")
        )

        targeting = {
            "geos": ["US-NY", "US-LA", "US-CHI", "US-SF"],
            "devices": ["desktop", "mobile"],
            "age_brackets": ["25-34", "35-44"],
            "audience_segments": ["site_visitors_7d", "lookalike_tier1"],
        }
        if cfg["goal"] == OptimizationGoal.reach:
            targeting["devices"] = ["ctv", "desktop", "mobile"]

        supply = SUPPLY_SOURCES_TIER1.copy()
        if cfg["pacing_rate"] < 0.70:
            supply += ["xandr", "sovrn"]

        creative_ids = [f"cre_{uuid.uuid4().hex[:6]}" for _ in range(3)]

        camp = Campaign(
            id=cid,
            name=cfg["name"],
            advertiser=cfg["advertiser"],
            status=cfg["status"],
            optimization_goal=cfg["goal"],
            daily_budget_usd=cfg["daily_budget"],
            total_budget_usd=cfg["total_budget"],
            spend_today_usd=round(spend, 2),
            spend_total_usd=round(spend * random.uniform(8, 22), 2),
            base_bid_cpm=cfg["base_bid"],
            bid_modifier=cfg["bid_modifier"],
            bid_floor_cpm=0.50,
            bid_ceiling_cpm=35.0,
            target_cpa=cfg.get("target_cpa"),
            target_roas=cfg.get("target_roas"),
            target_ctr=cfg.get("target_ctr"),
            impressions=imps,
            clicks=clicks,
            conversions=convs,
            revenue_usd=round(revenue, 2),
            targeting=targeting,
            supply_sources=supply,
            blocked_domains=["malware-site.com", "click-farm.net"],
            creative_ids=creative_ids,
            pacing_type="even",
            pacing_rate=cfg["pacing_rate"],
        )
        db.add(camp)

        # Seed campaign memory
        cpa = round(spend / convs, 2) if convs > 0 else None
        add_campaign_memory(
            cid, "performance_summary",
            f"Campaign '{cfg['name']}' ({cfg['advertiser']}): "
            f"pacing_rate={cfg['pacing_rate']}, spend=${spend:.0f}/{cfg['daily_budget']}, "
            f"impressions={imps}, conversions={convs}, CPA=${cpa}. "
            f"Goal: {cfg['goal']}. Issue: {cfg.get('issue', 'none')}.",
            {"campaign_name": cfg["name"], "advertiser": cfg["advertiser"]},
        )

    # Seed hourly snapshots
    for cid, cfg in zip(campaign_ids, SAMPLE_CAMPAIGNS):
        for h in range(23, -1, -1):
            ts = datetime.now(timezone.utc) - timedelta(hours=h)
            hourly_spend = cfg["daily_budget"] / 24 * cfg["pacing_rate"] * random.uniform(0.8, 1.2)
            snap = CampaignSnapshot(
                campaign_id=cid,
                hour_ts=ts,
                impressions=int(hourly_spend / 5 * 1000),
                clicks=int(hourly_spend / 5 * 1000 * 0.008),
                conversions=int(hourly_spend / 5 * 1000 * 0.008 * 0.04),
                spend_usd=round(hourly_spend, 2),
                revenue_usd=round(hourly_spend * random.uniform(1.5, 4.5), 2),
                avg_bid_cpm=cfg["base_bid"] * cfg["bid_modifier"],
                win_rate=random.uniform(0.15, 0.45),
                fill_rate=random.uniform(0.60, 0.90),
            )
            db.add(snap)

    # Seed A/B experiments
    if len(campaign_ids) >= 4:
        exp = Experiment(
            id=f"exp_{uuid.uuid4().hex[:8]}",
            name="Bid Modifier +15% Test — Nike Retargeting",
            description="Testing whether a 15% bid increase improves CPA on retargeting campaigns",
            hypothesis="Higher bids will secure better inventory, improving CVR and lowering CPA by 10%",
            metric="cpa",
            status="running",
            control_campaign_ids=[campaign_ids[0]],
            treatment_campaign_ids=[campaign_ids[2]],
            control_metric_value=32.50,
            treatment_metric_value=28.80,
            lift_pct=-11.4,
            p_value=0.038,
            is_significant=True,
            start_date=datetime.now(timezone.utc) - timedelta(days=7),
        )
        db.add(exp)

    await db.commit()

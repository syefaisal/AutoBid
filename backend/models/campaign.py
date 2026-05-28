from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, JSON, Enum as SAEnum
from sqlalchemy.sql import func
from models.db import Base
import enum


class CampaignStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    ended = "ended"
    pending = "pending"


class OptimizationGoal(str, enum.Enum):
    cpa = "cpa"
    roas = "roas"
    ctr = "ctr"
    reach = "reach"
    viewability = "viewability"


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    advertiser = Column(String, nullable=False)
    status = Column(SAEnum(CampaignStatus), default=CampaignStatus.active)
    optimization_goal = Column(SAEnum(OptimizationGoal), default=OptimizationGoal.cpa)

    # Budget
    daily_budget_usd = Column(Float, nullable=False)
    total_budget_usd = Column(Float, nullable=False)
    spend_today_usd = Column(Float, default=0.0)
    spend_total_usd = Column(Float, default=0.0)

    # Bidding
    base_bid_cpm = Column(Float, nullable=False)
    bid_floor_cpm = Column(Float, default=0.5)
    bid_ceiling_cpm = Column(Float, default=50.0)
    bid_modifier = Column(Float, default=1.0)

    # Performance targets
    target_cpa = Column(Float, nullable=True)
    target_roas = Column(Float, nullable=True)
    target_ctr = Column(Float, nullable=True)

    # Current performance
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    revenue_usd = Column(Float, default=0.0)

    # Targeting
    targeting = Column(JSON, default=dict)  # geo, demo, device, interest
    supply_sources = Column(JSON, default=list)  # SSP/exchange allowlist
    blocked_domains = Column(JSON, default=list)
    creative_ids = Column(JSON, default=list)

    # Pacing
    pacing_type = Column(String, default="even")  # even, front_loaded, back_loaded
    pacing_rate = Column(Float, default=1.0)  # 1.0 = on track

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class CampaignSnapshot(Base):
    """Hourly performance snapshot for time-series analysis."""
    __tablename__ = "campaign_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(String, nullable=False, index=True)
    hour_ts = Column(DateTime, nullable=False)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    spend_usd = Column(Float, default=0.0)
    revenue_usd = Column(Float, default=0.0)
    avg_bid_cpm = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
    fill_rate = Column(Float, default=0.0)

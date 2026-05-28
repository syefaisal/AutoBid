from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import get_db, Experiment

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.get("/")
async def list_experiments(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Experiment).order_by(Experiment.created_at.desc()))
    exps = result.scalars().all()
    return [
        {
            "id": e.id,
            "name": e.name,
            "description": e.description,
            "hypothesis": e.hypothesis,
            "metric": e.metric,
            "status": e.status,
            "control_campaign_ids": e.control_campaign_ids,
            "treatment_campaign_ids": e.treatment_campaign_ids,
            "control_metric_value": e.control_metric_value,
            "treatment_metric_value": e.treatment_metric_value,
            "lift_pct": e.lift_pct,
            "p_value": e.p_value,
            "is_significant": e.is_significant,
            "start_date": e.start_date.isoformat() if e.start_date else None,
            "end_date": e.end_date.isoformat() if e.end_date else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in exps
    ]

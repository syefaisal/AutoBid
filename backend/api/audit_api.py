from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from models import get_db, AuditLog
from agent.tools import approve_action, rollback_action

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/")
async def list_audit_logs(
    campaign_id: str = None,
    status: str = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    q = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
    if campaign_id:
        q = q.where(AuditLog.campaign_id == campaign_id)
    if status:
        q = q.where(AuditLog.status == status)
    result = await db.execute(q)
    logs = result.scalars().all()
    return [
        {
            "id": l.id,
            "trace_id": l.trace_id,
            "action_type": l.action_type,
            "campaign_id": l.campaign_id,
            "status": l.status,
            "is_dry_run": l.is_dry_run,
            "requires_approval": l.requires_approval,
            "approved_by": l.approved_by,
            "params_before": l.params_before,
            "params_requested": l.params_requested,
            "params_after": l.params_after,
            "agent_rationale": l.agent_rationale,
            "rag_sources": l.rag_sources,
            "latency_ms": l.latency_ms,
            "error_message": l.error_message,
            "created_at": l.created_at.isoformat() if l.created_at else None,
            "executed_at": l.executed_at.isoformat() if l.executed_at else None,
        }
        for l in logs
    ]


class ApproveRequest(BaseModel):
    approved_by: str = "campaign_manager"


@router.post("/{audit_id}/approve")
async def approve(audit_id: str, req: ApproveRequest, db: AsyncSession = Depends(get_db)):
    result = await approve_action(db, audit_id, req.approved_by)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{audit_id}/reject")
async def reject(audit_id: str, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import update
    from models.audit import ActionStatus
    result = await db.execute(select(AuditLog).where(AuditLog.id == audit_id))
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Not found")
    await db.execute(
        update(AuditLog).where(AuditLog.id == audit_id).values(status=ActionStatus.rejected)
    )
    await db.commit()
    return {"status": "rejected", "audit_id": audit_id}


@router.post("/{audit_id}/rollback")
async def rollback(audit_id: str, db: AsyncSession = Depends(get_db)):
    result = await rollback_action(db, audit_id, "api_user", "api")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

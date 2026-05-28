from fastapi import APIRouter, HTTPException
from telemetry.tracing import get_all_traces, serialize_trace

router = APIRouter(prefix="/traces", tags=["observability"])


@router.get("/")
async def list_traces(limit: int = 30):
    return get_all_traces(limit=limit)


@router.get("/{trace_id}")
async def get_trace(trace_id: str):
    data = serialize_trace(trace_id)
    if not data["spans"]:
        raise HTTPException(status_code=404, detail="Trace not found")
    return data

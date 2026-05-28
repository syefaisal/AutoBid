import json
import asyncio
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from langgraph.types import Command

from models import get_db, AgentSession
from agent.agent import AgentOrchestrator
from agent.graph import get_graph, make_thread_config, make_initial_state

router = APIRouter(prefix="/agent", tags=["agent"])


# ── Request / response models ─────────────────────────────────────────────────

class RunRequest(BaseModel):
    query: str
    dry_run: bool = False


class WorkflowRunRequest(BaseModel):
    goal: str
    dry_run: bool = False
    session_id: str | None = None
    require_approval: bool = True


class ResumeRequest(BaseModel):
    approved_ids: list[str] = []
    rejected_ids: list[str] = []


# ── Original single-agent SSE endpoint (kept for backwards-compat) ────────────

@router.post("/run")
async def run_agent(req: RunRequest, db: AsyncSession = Depends(get_db)):
    """Stream single-agent execution events as SSE."""
    orchestrator = AgentOrchestrator(db=db, is_dry_run=req.dry_run)

    async def event_stream():
        async for event in orchestrator.run(req.query):
            yield f"data: {json.dumps(event)}\n\n"
            await asyncio.sleep(0)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── LangGraph multi-agent workflow ────────────────────────────────────────────

@router.post("/workflow/run")
async def run_workflow(req: WorkflowRunRequest, db: AsyncSession = Depends(get_db)):
    """
    Start (or resume) a LangGraph multi-agent optimization workflow.
    Streams node-level events as SSE.

    Each SSE payload is a JSON dict with a `type` field. Notable types:
      plan_created, metrics_fetched, rag_retrieved, actions_proposed,
      action_approved, action_blocked, action_pending_approval, audit_complete,
      action_executed, review_complete, workflow_interrupted, workflow_complete
    """
    session_id = req.session_id or f"wf_{uuid.uuid4().hex[:12]}"
    trace_id = f"tr_{uuid.uuid4().hex[:12]}"

    graph = get_graph(require_approval=req.require_approval)
    thread_cfg = make_thread_config(session_id, db)
    initial_state = make_initial_state(
        user_goal=req.goal,
        session_id=session_id,
        trace_id=trace_id,
        dry_run=req.dry_run,
        require_approval=req.require_approval,
    )

    async def event_stream():
        try:
            yield _sse({"type": "workflow_start", "session_id": session_id,
                        "trace_id": trace_id, "goal": req.goal})

            async for event in graph.astream_events(
                initial_state, config=thread_cfg, version="v2"
            ):
                kind = event.get("event")
                name = event.get("name", "")

                # Node start / end lifecycle events
                if kind == "on_chain_start" and name in _NODE_NAMES:
                    yield _sse({"type": "node_start", "node": name})
                elif kind == "on_chain_end" and name in _NODE_NAMES:
                    output = event.get("data", {}).get("output", {})
                    # Forward all stream_events the node emitted
                    for se in output.get("stream_events", []):
                        yield _sse(se)
                    yield _sse({"type": "node_end", "node": name})

            # Check if the graph is now interrupted (waiting for human approval)
            state_snapshot = graph.get_state(thread_cfg)
            if state_snapshot.next:
                # Graph paused — surface ALL actions queued for execution so the
                # human can approve or reject each one individually.
                pending_approval = state_snapshot.values.get("pending_approval_actions", [])
                auto_approved   = state_snapshot.values.get("approved_actions", [])

                def _action_dict(a, approval_required: bool) -> dict:
                    if isinstance(a, dict):
                        return {
                            "action_id":        a.get("action_id", ""),
                            "action_type":      a.get("action_type", ""),
                            "campaign_id":      a.get("campaign_id", ""),
                            "params":           a.get("params", {}),
                            "rationale":        a.get("rationale", ""),
                            "approval_required": approval_required,
                        }
                    return {
                        "action_id":        a.action_id,
                        "action_type":      a.action_type,
                        "campaign_id":      a.campaign_id,
                        "params":           a.params,
                        "rationale":        a.rationale,
                        "approval_required": approval_required,
                    }

                all_actions = [
                    *[_action_dict(a, True)  for a in pending_approval],
                    *[_action_dict(a, False) for a in auto_approved],
                ]
                yield _sse({
                    "type": "workflow_interrupted",
                    "session_id": session_id,
                    "pending_actions": all_actions,
                    "resume_url": f"/agent/sessions/{session_id}/resume",
                })
            else:
                final = state_snapshot.values
                yield _sse({
                    "type": "workflow_complete",
                    "session_id": session_id,
                    "review_summary": final.get("review_summary", ""),
                    "optimization_complete": final.get("optimization_complete", True),
                    "actions_executed": len(final.get("executed_results", [])),
                    "actions_blocked": len(final.get("blocked_actions", [])),
                })

        except Exception as exc:
            yield _sse({"type": "error", "error": str(exc)})
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{session_id}/resume")
async def resume_workflow(
    session_id: str,
    req: ResumeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Resume an interrupted workflow after human approval decisions.
    Streams remaining execution events as SSE.
    """
    graph = get_graph(require_approval=True)
    thread_cfg = make_thread_config(session_id, db)

    state_snapshot = graph.get_state(thread_cfg)
    if not state_snapshot.next:
        raise HTTPException(status_code=409, detail="Workflow is not waiting for approval")

    human_decision = {
        "approved_ids": req.approved_ids,
        "rejected_ids": req.rejected_ids,
    }

    async def event_stream():
        try:
            yield _sse({"type": "workflow_resumed", "session_id": session_id,
                        "approved": len(req.approved_ids),
                        "rejected": len(req.rejected_ids)})

            async for event in graph.astream_events(
                Command(resume=human_decision),
                config=thread_cfg,
                version="v2",
            ):
                kind = event.get("event")
                name = event.get("name", "")

                if kind == "on_chain_start" and name in _NODE_NAMES:
                    yield _sse({"type": "node_start", "node": name})
                elif kind == "on_chain_end" and name in _NODE_NAMES:
                    output = event.get("data", {}).get("output", {})
                    for se in output.get("stream_events", []):
                        yield _sse(se)
                    yield _sse({"type": "node_end", "node": name})

            final_state = graph.get_state(thread_cfg).values
            yield _sse({
                "type": "workflow_complete",
                "session_id": session_id,
                "review_summary": final_state.get("review_summary", ""),
                "optimization_complete": final_state.get("optimization_complete", True),
                "actions_executed": len(final_state.get("executed_results", [])),
                "actions_blocked": len(final_state.get("blocked_actions", [])),
            })

        except Exception as exc:
            yield _sse({"type": "error", "error": str(exc)})
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions/{session_id}/state")
async def get_workflow_state(session_id: str, db: AsyncSession = Depends(get_db)):
    """Return current LangGraph state snapshot for a workflow session."""
    graph = get_graph()
    thread_cfg = make_thread_config(session_id, db)
    try:
        snapshot = graph.get_state(thread_cfg)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    v = snapshot.values
    return {
        "session_id": session_id,
        "next_nodes": list(snapshot.next),
        "is_interrupted": bool(snapshot.next),
        "plan_title": v.get("plan_title"),
        "plan_steps": v.get("plan_steps", []),
        "current_step_idx": v.get("current_step_idx", 0),
        "iteration_count": v.get("iteration_count", 1),
        "optimization_complete": v.get("optimization_complete", False),
        "review_summary": v.get("review_summary"),
        "actions_executed": len(v.get("executed_results", [])),
        "actions_blocked": len(v.get("blocked_actions", [])),
        "pending_approval_actions": v.get("pending_approval_actions", []),
    }


# ── Original session endpoints ────────────────────────────────────────────────

@router.get("/sessions")
async def list_sessions(limit: int = 20, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AgentSession).order_by(desc(AgentSession.created_at)).limit(limit)
    )
    sessions = result.scalars().all()
    return [
        {
            "id": s.id,
            "trace_id": s.trace_id,
            "query": s.user_query[:100],
            "status": s.status,
            "is_dry_run": s.is_dry_run,
            "tool_calls": s.tool_calls_count,
            "rag_retrievals": s.rag_retrievals_count,
            "actions_taken": s.actions_taken,
            "total_latency_ms": s.total_latency_ms,
            "tokens_in": s.total_tokens_input,
            "tokens_out": s.total_tokens_output,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentSession).where(AgentSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "id": session.id,
        "trace_id": session.trace_id,
        "query": session.user_query,
        "final_answer": session.final_answer,
        "status": session.status,
        "is_dry_run": session.is_dry_run,
        "tool_calls": session.tool_calls_count,
        "rag_retrievals": session.rag_retrievals_count,
        "total_latency_ms": session.total_latency_ms,
        "tokens_in": session.total_tokens_input,
        "tokens_out": session.total_tokens_output,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

_NODE_NAMES = {"planner", "analyst", "optimizer", "auditor", "executor", "reviewer"}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"

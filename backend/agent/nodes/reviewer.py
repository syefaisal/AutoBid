"""
Reviewer Node — post-execution synthesis agent.
Reads executed results, checks against targets, decides if more iterations needed.
"""
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from agent.state import AutoBidState, PlanStep
from config import settings

SYSTEM = """\
You are AutoBid Reviewer, the quality-assurance component of a campaign optimization workflow.

You receive a summary of what was just executed and the original plan.
Your job is to:
1. Summarize what was accomplished this iteration (be specific — dollars, percentages, IDs).
2. Evaluate whether the optimization goal was fully addressed or needs another iteration.
3. Identify any campaigns that still need attention.
4. Note any unexpected results or warnings.

Set `optimization_complete = true` only when:
- All plan steps have been executed, AND
- No critical pacing or performance issues remain unaddressed, AND
- All approved actions executed successfully.

If another iteration would be valuable, set `optimization_complete = false` and
describe in `next_iteration_notes` what the next analyst pass should focus on.

Keep your summary concise and actionable — campaign managers are busy.
"""

REVIEW_TOOL = {
    "name": "submit_review",
    "description": "Submit the post-execution review.",
    "input_schema": {
        "type": "object",
        "required": ["summary", "optimization_complete"],
        "properties": {
            "summary":               {"type": "string"},
            "optimization_complete": {"type": "boolean"},
            "next_iteration_notes":  {"type": "string"},
        }
    }
}


async def reviewer_node(state: AutoBidState, config: RunnableConfig) -> dict:
    """Synthesize results and decide if optimization is complete."""
    executed = state.executed_results
    plan_steps = state.plan_steps
    blocked = state.blocked_actions
    pending = state.pending_approval_actions

    idx = state.current_step_idx
    updated_steps = list(plan_steps)
    if idx < len(updated_steps):
        updated_steps[idx] = updated_steps[idx].model_copy(update={"status": "completed"})

    exec_summary = _format_results(executed)
    plan_summary = _format_plan(updated_steps)

    llm = ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        max_tokens=1500,
    ).bind_tools([REVIEW_TOOL], tool_choice={"type": "tool", "name": "submit_review"})

    messages = [
        SystemMessage(content=SYSTEM),
        HumanMessage(content=(
            f"ORIGINAL GOAL: {state.user_goal}\n\n"
            f"PLAN STATUS:\n{plan_summary}\n\n"
            f"EXECUTED ACTIONS:\n{exec_summary}\n\n"
            f"BLOCKED ACTIONS: {len(blocked)}\n"
            f"PENDING HUMAN APPROVAL: {len(pending)}\n"
            f"DRY RUN: {state.dry_run}\n"
            f"ITERATION: {state.iteration_count}\n\n"
            "Produce your review now."
        ))
    ]

    response = await llm.ainvoke(messages)

    review_data = {"summary": "Review complete.", "optimization_complete": True,
                   "next_iteration_notes": ""}
    for block in response.tool_calls:
        if block["name"] == "submit_review":
            review_data = block["args"]
            break

    if state.iteration_count >= 3:
        review_data["optimization_complete"] = True
        review_data["next_iteration_notes"] = "Max iterations reached."

    next_idx = idx + 1
    if next_idx >= len(plan_steps):
        review_data["optimization_complete"] = True

    return {
        "plan_steps": updated_steps,
        "current_step_idx": next_idx,
        "review_summary": review_data["summary"],
        "optimization_complete": review_data.get("optimization_complete", True),
        "next_iteration_notes": review_data.get("next_iteration_notes", ""),
        "iteration_count": state.iteration_count + 1,
        "messages": [*messages, response],
        "stream_events": [{
            "type": "review_complete",
            "summary": review_data["summary"],
            "optimization_complete": review_data.get("optimization_complete", True),
            "next_iteration_notes": review_data.get("next_iteration_notes", ""),
            "steps_completed": sum(1 for s in updated_steps if s.status == "completed"),
            "steps_total": len(updated_steps),
        }],
    }


def _format_results(executed: list) -> str:
    if not executed:
        return "No actions executed this iteration."
    lines = []
    for r in executed:
        lines.append(
            f"  [{r.action_type}] {r.campaign_id} "
            f"status={r.status} audit_id={r.audit_id}"
        )
    return "\n".join(lines)


def _format_plan(steps: list[PlanStep]) -> str:
    status_icons = {"pending": "○", "in_progress": "→", "completed": "✓", "skipped": "—"}
    lines = []
    for s in steps:
        icon = status_icons.get(s.status, "?")
        lines.append(f"  {icon} [{s.priority.upper()}] {s.title} ({s.status})")
    return "\n".join(lines)

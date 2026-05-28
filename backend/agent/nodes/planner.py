"""
Planner Node — breaks the user's optimization goal into a structured, ordered plan.
Uses Claude with a structured-output tool so the plan is machine-readable.
"""
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from agent.state import AutoBidState, PlanStep
from config import settings

SYSTEM = """\
You are AutoBid Planner, the strategic reasoning component of an AI campaign optimization system.

Your ONLY job in this turn is to analyze the user's optimization goal and produce a clear,
executable plan — a sequence of concrete steps that the downstream agents (Analyst, Optimizer,
Auditor, Executor) will carry out.

## Step Types Available
- analyze          : gather metrics + RAG context for campaign(s)
- optimize_bid     : adjust bid modifiers based on performance
- update_budget    : change daily budget allocation
- update_targeting : broaden or tighten targeting constraints
- update_supply    : add/remove SSP/exchange sources
- route_creative   : reweight creatives
- review           : post-execution performance check

## Planning Rules
1. Always start with at least one "analyze" step to ground decisions in data.
2. Group related campaigns together when they share the same issue.
3. Higher-impact actions (budget changes, pauses) go last — after validation.
4. Max 8 steps per plan — be focused, not exhaustive.
5. Each step must name the specific campaign(s) or use [] for "all active campaigns".

Call the `create_plan` tool to output your plan. Do not produce free-form text — only the tool call.
"""

CREATE_PLAN_TOOL = {
    "name": "create_plan",
    "description": "Output the structured optimization plan.",
    "input_schema": {
        "type": "object",
        "required": ["title", "steps"],
        "properties": {
            "title": {
                "type": "string",
                "description": "One-line summary of what this plan achieves"
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["step_id", "title", "description", "step_type",
                                 "campaign_ids", "priority"],
                    "properties": {
                        "step_id":      {"type": "string"},
                        "title":        {"type": "string"},
                        "description":  {"type": "string"},
                        "step_type":    {
                            "type": "string",
                            "enum": ["analyze", "optimize_bid", "update_budget",
                                     "update_targeting", "update_supply",
                                     "route_creative", "review"]
                        },
                        "campaign_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific campaign IDs, or [] for all active"
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["high", "medium", "low"]
                        },
                    }
                }
            }
        }
    }
}


async def planner_node(state: AutoBidState, config: RunnableConfig) -> dict:
    """Generate a structured plan from the user's goal."""
    db = config["configurable"]["db"]

    from sqlalchemy import select
    from models.campaign import Campaign, CampaignStatus
    result = await db.execute(
        select(Campaign.id, Campaign.name, Campaign.advertiser,
               Campaign.status, Campaign.pacing_rate, Campaign.optimization_goal)
        .where(Campaign.status == CampaignStatus.active)
    )
    campaigns = result.all()

    campaign_summary = "\n".join(
        f"  - {c.id}: '{c.name}' ({c.advertiser}) "
        f"goal={c.optimization_goal} pacing={c.pacing_rate:.2f}"
        for c in campaigns
    )

    llm = ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        max_tokens=2048,
    ).bind_tools([CREATE_PLAN_TOOL], tool_choice={"type": "tool", "name": "create_plan"})

    messages = [
        SystemMessage(content=SYSTEM),
        HumanMessage(content=(
            f"USER GOAL: {state.user_goal}\n\n"
            f"ACTIVE CAMPAIGNS:\n{campaign_summary}\n\n"
            f"DRY RUN: {state.dry_run}\n\n"
            "Produce the plan now."
        ))
    ]

    response = await llm.ainvoke(messages)

    plan_data = {"title": "Optimization Plan", "steps": []}
    for block in response.tool_calls:
        if block["name"] == "create_plan":
            plan_data = block["args"]
            break

    plan_steps: list[PlanStep] = [
        PlanStep(
            step_id=s.get("step_id", f"step_{i+1}"),
            title=s["title"],
            description=s["description"],
            step_type=s["step_type"],
            campaign_ids=s.get("campaign_ids", []),
            priority=s.get("priority", "medium"),
            status="pending",
        )
        for i, s in enumerate(plan_data.get("steps", []))
    ]

    return {
        "plan_title": plan_data["title"],
        "plan_steps": plan_steps,
        "current_step_idx": 0,
        "messages": [*messages, response],
        "stream_events": [{
            "type": "plan_created",
            "title": plan_data["title"],
            "step_count": len(plan_steps),
            "steps": [
                {
                    "step_id": s.step_id,
                    "title": s.title,
                    "step_type": s.step_type,
                    "priority": s.priority,
                    "status": s.status,
                }
                for s in plan_steps
            ],
        }],
    }

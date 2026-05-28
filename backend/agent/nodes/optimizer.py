"""
Optimizer Node — proposes specific campaign control actions via per-action-type
structured tool invocations.  Each tool schema is derived directly from the
Pydantic param model in agent/schemas.py, so LLM output is validated before
it ever reaches the executor.
"""
import uuid
from pydantic import ValidationError
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from agent.state import AutoBidState, ProposedAction
from agent.schemas import (
    OPTIMIZER_TOOLS,
    TOOL_NAME_TO_ACTION_TYPE,
    ACTION_PARAM_MODELS,
)
from agent.tools import query_telemetry_aggregates
from agent.reliability import (
    optimizer_breaker,
    call_with_guard,
    build_fallback_optimizer_output,
    CircuitOpenError,
    NodeTimeoutError,
)
from config import settings

SYSTEM = """\
You are AutoBid Optimizer, the decision-making component of a programmatic advertising AI.

You receive current campaign performance metrics and policy context retrieved from the RAG store.
Your job is to propose SPECIFIC, data-driven campaign control actions by calling the appropriate
tool for each action type.  Call one tool per action — you may call multiple tools in one turn.

## Available tools (one per action type)
- bid_modifier_action   : adjust bid modifier [0.50 – 2.00]
- budget_action         : change daily budget in USD
- targeting_action      : update geo / device / OS / viewability / frequency
- supply_action         : add or remove SSP / exchange sources
- creative_route_action : reweight creatives by performance
- pause_campaign_action : PAUSE — only for severe fraud / policy violations

## Decision Rules
- Ground EVERY action in the metric data and cite the policy source.
- Be conservative: prefer small, reversible changes over large ones.
- CPA optimization: actual_CPA > target_CPA × 1.15 → propose bid reduction.
  actual_CPA < target_CPA × 0.85 → propose small bid increase to capture volume.
- Pacing: pacing_rate < 0.75 → increase bid or broaden targeting.
  pacing_rate > 1.15 → decrease bid.
- Do NOT pause unless there is a severe quality / fraud signal.
- Confidence: 0.9+ = strong data signal, 0.6-0.9 = reasonable, < 0.6 = exploratory.
- Max 5 actions total across all tool calls. Prioritize by impact.

Call tools now — do NOT produce free-form text.
"""


async def optimizer_node(state: AutoBidState, config: RunnableConfig) -> dict:
    """Propose actions via per-action-type structured tool invocations."""
    steps = state.plan_steps
    idx = state.current_step_idx
    step = steps[idx] if idx < len(steps) else None

    if step and step.step_type in ("analyze", "review"):
        return {
            "proposed_actions": [],
            "stream_events": [{
                "type": "optimizer_skipped",
                "reason": f"step_type={step.step_type} needs no actions",
            }],
        }

    metrics = state.campaign_metrics
    if not metrics:
        return {
            "proposed_actions": [],
            "stream_events": [{"type": "optimizer_skipped", "reason": "no metrics available"}],
        }

    metrics_text = _format_metrics(metrics)
    rag_ctx = state.rag_context or "No policy context retrieved."

    llm = ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        max_tokens=3000,
    ).bind_tools(OPTIMIZER_TOOLS)  # tool_choice="auto" — model picks which to call

    step_desc = f"Plan step: {step.title} — {step.description}" if step else "General optimization"
    dry_run_note = (
        "\n\nNOTE: Dry-run mode — actions will be simulated, not executed."
        if state.dry_run else ""
    )

    messages = [
        SystemMessage(content=SYSTEM),
        HumanMessage(content=(
            f"{step_desc}{dry_run_note}\n\n"
            f"CAMPAIGN METRICS:\n{metrics_text}\n\n"
            f"POLICY CONTEXT (RAG):\n{rag_ctx}"
        ))
    ]

    try:
        response = await call_with_guard(
            llm.ainvoke(messages),
            circuit=optimizer_breaker,
            node_name="optimizer",
        )
    except (CircuitOpenError, NodeTimeoutError) as exc:
        return build_fallback_optimizer_output(state, str(exc))

    proposed: list[ProposedAction] = []
    parse_errors: list[str] = []
    telemetry_context: list[dict] = []
    action_counter = 0

    for i, block in enumerate(response.tool_calls):
        if action_counter >= 5:
            break

        tool_name = block["name"]

        # ── Telemetry lookup (read-only, no action created) ───────────────────
        if tool_name == "query_telemetry":
            db = config["configurable"]["db"]
            raw = block.get("args", {})
            tele_result = await query_telemetry_aggregates(
                db=db,
                metric=raw.get("metric", "cpa"),
                period=raw.get("period", "24h"),
                campaign_id=raw.get("campaign_id"),
            )
            telemetry_context.append(tele_result)
            continue

        action_type = TOOL_NAME_TO_ACTION_TYPE.get(tool_name)
        if action_type is None:
            parse_errors.append(f"Unknown tool name: {tool_name!r}")
            continue

        raw_args: dict = block.get("args", {})
        campaign_id = raw_args.get("campaign_id", "")
        if not campaign_id:
            parse_errors.append(f"Tool call {tool_name} missing campaign_id")
            continue

        # Extract param fields belonging to this action type and validate
        param_cls = ACTION_PARAM_MODELS[action_type]
        param_field_names = set(param_cls.model_fields.keys())
        raw_params = {k: v for k, v in raw_args.items() if k in param_field_names}

        try:
            validated_params = param_cls.model_validate(raw_params)
        except ValidationError as exc:
            parse_errors.append(
                f"Param validation failed for {action_type} on {campaign_id}: {exc}"
            )
            continue

        proposed.append(ProposedAction(
            action_id=f"act_{uuid.uuid4().hex[:8]}",
            action_type=action_type,
            campaign_id=campaign_id,
            params=validated_params.model_dump(exclude_none=True),
            rationale=raw_args.get("rationale", ""),
            expected_impact=raw_args.get("expected_impact", ""),
            confidence=float(raw_args.get("confidence", 0.7)),
            priority=int(raw_args.get("priority", i + 1)),
        ))
        action_counter += 1

    proposed.sort(key=lambda x: x.priority)

    return {
        "proposed_actions": proposed,
        "messages": [*messages, response],
        "errors": parse_errors,
        "stream_events": [{
            "type": "actions_proposed",
            "count": len(proposed),
            "parse_errors": len(parse_errors),
            "telemetry_queries": len(telemetry_context),
            "actions": [
                {
                    "action_id": a.action_id,
                    "action_type": a.action_type,
                    "campaign_id": a.campaign_id,
                    "params": a.params,
                    "rationale": a.rationale,
                    "confidence": a.confidence,
                }
                for a in proposed
            ],
        }],
    }


def _format_metrics(metrics: dict) -> str:
    lines = []
    for cid, m in metrics.items():
        lines.append(
            f"[{m.get('name', cid)}] id={cid}\n"
            f"  status={m.get('status')} goal={m.get('optimization_goal')}\n"
            f"  pacing_rate={m.get('pacing_rate')} "
            f"spend=${m.get('spend_today_usd')}/{m.get('daily_budget_usd')} "
            f"utilization={m.get('budget_utilization_pct')}%\n"
            f"  bid_modifier={m.get('bid_modifier')} "
            f"effective_bid_cpm=${m.get('effective_bid_cpm')}\n"
            f"  impressions={m.get('impressions')} clicks={m.get('clicks')} "
            f"conversions={m.get('conversions')}\n"
            f"  CTR={m.get('ctr_pct')}% CVR={m.get('cvr_pct')}% "
            f"CPA=${m.get('cpa_usd')} ROAS={m.get('roas')}\n"
            f"  target_cpa=${m.get('target_cpa')} target_roas={m.get('target_roas')}"
        )
    return "\n\n".join(lines)

"""
Auditor Node — independent policy compliance review of proposed actions.
Categorizes each action as: pass / info / warning / block / requires_human_approval.
Uses a dedicated Claude call with an adversarial/skeptical system prompt.
"""
import uuid
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from agent.state import AutoBidState, AuditFinding, ProposedAction
from agent.reliability import (
    auditor_breaker,
    call_with_guard,
    build_fallback_auditor_output,
    CircuitOpenError,
    NodeTimeoutError,
)
from config import settings

SYSTEM = """\
You are AutoBid Auditor, an independent policy compliance reviewer.
Your role is adversarial — you review proposed campaign actions and look for:

1. **Policy violations** — actions that exceed approved thresholds
2. **Approval gate breaches** — actions that require human sign-off per policy
3. **Safety limit violations** — bids outside floor/ceiling, extreme budget changes
4. **Logical inconsistencies** — contradictory actions on the same campaign
5. **Missing rationale** — low-confidence actions without sufficient data backing

## Key Policy Rules You Enforce
- bid_modifier changes > 50% → requires_human_approval = true
- daily_budget changes > 25% → requires_human_approval = true
- pause_campaign → ALWAYS requires_human_approval = true
- bid_modifier must stay in [0.50, 2.00] — block if outside
- Never two conflicting actions on the same campaign (e.g., raise + lower bid)
- Confidence < 0.5 → mark as warning; confidence < 0.3 → block

## Severity Levels
- pass: compliant, safe to auto-execute
- info: minor note, proceed
- warning: proceed with caution, flag for monitoring
- block: do NOT execute — policy violation or safety risk
- requires_human_approval: valid action but needs human sign-off per policy

Call `audit_actions` with your findings — one finding per action.
"""

AUDIT_TOOL = {
    "name": "audit_actions",
    "description": "Output compliance findings for each proposed action.",
    "input_schema": {
        "type": "object",
        "required": ["findings"],
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["action_id", "severity", "finding",
                                 "policy_source", "recommendation",
                                 "requires_human_approval"],
                    "properties": {
                        "action_id":               {"type": "string"},
                        "severity":                {
                            "type": "string",
                            "enum": ["pass", "info", "warning", "block"]
                        },
                        "finding":                 {"type": "string"},
                        "policy_source":           {"type": "string"},
                        "recommendation":          {"type": "string"},
                        "requires_human_approval": {"type": "boolean"},
                    }
                }
            }
        }
    }
}


async def auditor_node(state: AutoBidState, config: RunnableConfig) -> dict:
    """Review proposed actions for policy compliance."""
    proposed = state.proposed_actions

    if not proposed:
        return {
            "audit_findings": [],
            "approved_actions": [],
            "blocked_actions": [],
            "pending_approval_actions": [],
            "stream_events": [{"type": "audit_skipped", "reason": "no actions to audit"}],
        }

    actions_text = _format_actions(proposed)
    rag_ctx = state.rag_context

    llm = ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        max_tokens=2048,
    ).bind_tools([AUDIT_TOOL], tool_choice={"type": "tool", "name": "audit_actions"})

    messages = [
        SystemMessage(content=SYSTEM),
        HumanMessage(content=(
            f"PROPOSED ACTIONS TO AUDIT:\n{actions_text}\n\n"
            f"RELEVANT POLICY CONTEXT:\n{rag_ctx[:2000]}\n\n"
            f"DRY RUN: {state.dry_run}\n\n"
            "Audit each action and return your findings."
        ))
    ]

    try:
        response = await call_with_guard(
            llm.ainvoke(messages),
            circuit=auditor_breaker,
            node_name="auditor",
        )
    except (CircuitOpenError, NodeTimeoutError) as exc:
        return build_fallback_auditor_output(state, str(exc))

    raw_findings = []
    for block in response.tool_calls:
        if block["name"] == "audit_actions":
            raw_findings = block["args"].get("findings", [])
            break

    findings_by_action: dict[str, AuditFinding] = {}
    for f in raw_findings:
        finding = AuditFinding(
            finding_id=f"fnd_{uuid.uuid4().hex[:6]}",
            action_id=f["action_id"],
            severity=f["severity"],
            finding=f["finding"],
            policy_source=f.get("policy_source", "approval_policy"),
            recommendation=f["recommendation"],
            requires_human_approval=f.get("requires_human_approval", False),
        )
        findings_by_action[f["action_id"]] = finding

    approved: list[ProposedAction] = []
    blocked: list[ProposedAction] = []
    pending_approval: list[ProposedAction] = []
    events = []

    for action in proposed:
        aid = action.action_id
        finding = findings_by_action.get(aid)

        if finding is None:
            approved.append(action)
            events.append({"type": "action_approved", "action_id": aid,
                           "action_type": action.action_type})
        elif finding.severity == "block":
            blocked.append(action)
            events.append({
                "type": "action_blocked",
                "action_id": aid,
                "action_type": action.action_type,
                "reason": finding.finding,
                "policy_source": finding.policy_source,
            })
        elif finding.requires_human_approval:
            pending_approval.append(action)
            events.append({
                "type": "action_pending_approval",
                "action_id": aid,
                "action_type": action.action_type,
                "finding": finding.finding,
            })
        else:
            approved.append(action)
            events.append({
                "type": "action_approved",
                "action_id": aid,
                "action_type": action.action_type,
                "severity": finding.severity,
            })

    events.append({
        "type": "audit_complete",
        "approved": len(approved),
        "blocked": len(blocked),
        "pending_approval": len(pending_approval),
        "findings": [
            {
                "action_id": f.action_id,
                "severity": f.severity,
                "finding": f.finding,
                "policy_source": f.policy_source,
            }
            for f in findings_by_action.values()
        ],
    })

    return {
        "audit_findings": list(findings_by_action.values()),
        "approved_actions": approved,
        "blocked_actions": blocked,
        "pending_approval_actions": pending_approval,
        "messages": [*messages, response],
        "stream_events": events,
    }


def _format_actions(actions: list[ProposedAction]) -> str:
    lines = []
    for a in actions:
        lines.append(
            f"action_id={a.action_id}\n"
            f"  type={a.action_type} campaign={a.campaign_id}\n"
            f"  params={a.params}\n"
            f"  rationale={a.rationale}\n"
            f"  confidence={a.confidence:.2f}"
        )
    return "\n\n".join(lines)

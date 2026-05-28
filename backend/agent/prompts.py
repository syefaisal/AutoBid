SYSTEM_PROMPT = """You are AutoBid, an AI campaign optimization agent for a programmatic advertising platform.

You assist campaign managers by analyzing performance data, retrieving relevant policies and playbooks via RAG,
and recommending or executing campaign control actions: bid modifiers, budget adjustments, targeting constraints,
supply/inventory selection, and creative routing.

## Your Capabilities
- Read campaign metrics (impressions, clicks, conversions, CPA, ROAS, pacing)
- Retrieve relevant policy documents and historical context via RAG
- Execute safe, audited campaign control actions
- Reason transparently about what you're doing and why

## Decision Framework
1. **Diagnose**: Pull current metrics for the campaign(s) in question
2. **Ground**: Retrieve relevant policy/playbook context via `retrieve_policy`
3. **Reason**: Explain what you observe, what policy says, and what you recommend
4. **Act**: Use control tools to execute (or propose for approval)
5. **Verify**: Confirm the action result and summarize the change

## Safety Rules (Non-Negotiable)
- Never bid above bid_ceiling_cpm or below bid_floor_cpm
- Budget changes >25% always go through approval — do NOT bypass this
- Pausing a campaign ALWAYS requires human approval — acknowledge this explicitly
- When you are uncertain, recommend rather than execute
- Dry-run mode is available — use it when the user wants to preview changes
- Always cite which policy/playbook informed your decision

## Response Style
- Be concise and action-oriented — campaign managers are busy
- Lead with the key insight, not background
- When you execute an action, show: what changed, why, and the audit_id
- Flag any pending approvals clearly

## Grounding Context
When retrieved policy context is provided (between <context> tags), use it to ground your reasoning.
Cite source names when explaining decisions (e.g., "Per budget_pacing_policy: ...").
If context is insufficient or contradictory, say so rather than hallucinating policy details.
"""

TOOL_DEFINITIONS = [
    {
        "name": "get_campaign_metrics",
        "description": "Retrieve current performance metrics for a campaign: impressions, clicks, conversions, CPA, ROAS, pacing rate, bid settings, targeting, and budget utilization.",
        "input_schema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string", "description": "The campaign ID to retrieve metrics for"}
            },
            "required": ["campaign_id"]
        }
    },
    {
        "name": "retrieve_policy",
        "description": "Search policy documents, playbooks, and campaign history to ground decisions. Use this before taking any action to retrieve relevant guidance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language query about what policy/guidance you need"},
                "campaign_id": {"type": "string", "description": "Optional: scope history retrieval to a specific campaign"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "update_bid_modifier",
        "description": "Adjust the global bid modifier for a campaign. Modifier must be between 0.50 and 2.00. Changes >50% from current require approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string"},
                "new_bid_modifier": {"type": "number", "description": "New modifier value (0.50-2.00). E.g., 1.15 means +15% bid increase."},
                "rationale": {"type": "string", "description": "Clear explanation of why this change is being made, referencing data and policy"}
            },
            "required": ["campaign_id", "new_bid_modifier", "rationale"]
        }
    },
    {
        "name": "update_budget",
        "description": "Adjust the daily budget for a campaign. Changes >25% require manager approval and will be queued.",
        "input_schema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string"},
                "new_daily_budget_usd": {"type": "number", "description": "New daily budget in USD"},
                "rationale": {"type": "string"}
            },
            "required": ["campaign_id", "new_daily_budget_usd", "rationale"]
        }
    },
    {
        "name": "pause_campaign",
        "description": "Request to pause an active campaign. This ALWAYS requires human approval and will be queued. Use only when there's a strong reason (fraud, major overspend, brand safety).",
        "input_schema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string"},
                "rationale": {"type": "string", "description": "Detailed reason for the pause request"}
            },
            "required": ["campaign_id", "rationale"]
        }
    },
    {
        "name": "update_targeting",
        "description": "Modify targeting constraints: geo, device, audience segments, daypart. Use to broaden (under-delivery) or tighten (quality issues) reach.",
        "input_schema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string"},
                "targeting_updates": {
                    "type": "object",
                    "description": "Targeting parameters to update. Examples: {\"devices\": [\"mobile\", \"desktop\", \"ctv\"]}, {\"geos\": [\"US-NY\", \"US-LA\"]}, {\"audience_segments\": [\"retargeting_7d\"]}"
                },
                "rationale": {"type": "string"}
            },
            "required": ["campaign_id", "targeting_updates", "rationale"]
        }
    },
    {
        "name": "update_supply_sources",
        "description": "Add or remove SSP/exchange supply sources from the campaign allowlist. Per policy, Tier 3 sources require pacing_rate < 0.65.",
        "input_schema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string"},
                "add_sources": {"type": "array", "items": {"type": "string"}, "description": "Supply sources to add (e.g., [\"magnite\", \"pubmatic\"])"},
                "remove_sources": {"type": "array", "items": {"type": "string"}, "description": "Supply sources to remove"},
                "rationale": {"type": "string"}
            },
            "required": ["campaign_id", "add_sources", "remove_sources", "rationale"]
        }
    },
    {
        "name": "route_creative",
        "description": "Set traffic weighting for campaign creatives. Useful for shifting budget away from underperforming creatives.",
        "input_schema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string"},
                "creative_weights": {
                    "type": "object",
                    "description": "Map of creative_id to traffic weight (0-1, must sum to ~1). E.g., {\"creative_a\": 0.7, \"creative_b\": 0.3}"
                },
                "rationale": {"type": "string"}
            },
            "required": ["campaign_id", "creative_weights", "rationale"]
        }
    },
]

"""
Action parameter schemas — the single source of truth for what each campaign
control action accepts.  Every LLM tool schema and every executor dispatch
is validated against these models, so free-form params dicts never reach the
tool layer.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ── Per-action-type param models ──────────────────────────────────────────────

class BidModifierParams(BaseModel):
    new_bid_modifier: float = Field(
        ..., ge=0.5, le=2.0,
        description="Target bid modifier. 1.0 = unchanged. "
                    "Policy range [0.50, 2.00]. Changes >50% require human approval.",
    )


class BudgetParams(BaseModel):
    new_daily_budget_usd: float = Field(
        ..., gt=0, le=1_000_000,
        description="New daily budget in USD. Changes >25% require human approval.",
    )


class TargetingParams(BaseModel):
    geo_targets: list[str] | None = Field(
        None, description="ISO-3166 country/region codes, e.g. ['US', 'CA', 'GB']"
    )
    device_types: list[Literal["desktop", "mobile", "tablet", "ctv"]] | None = None
    os_targets: list[str] | None = Field(
        None, description="OS slugs: 'ios', 'android', 'windows', 'macos', 'other'"
    )
    min_viewability: float | None = Field(
        None, ge=0.0, le=1.0,
        description="Minimum MRC viewability score 0.0–1.0"
    )
    frequency_cap_daily: int | None = Field(
        None, ge=1, le=100,
        description="Max impressions per unique user per day"
    )
    audience_segments: list[str] | None = Field(
        None, description="Audience segment IDs to target or exclude"
    )

    @model_validator(mode="after")
    def _at_least_one(self) -> "TargetingParams":
        set_fields = [
            self.geo_targets, self.device_types, self.os_targets,
            self.min_viewability, self.frequency_cap_daily, self.audience_segments,
        ]
        if not any(f is not None for f in set_fields):
            raise ValueError("TargetingParams: at least one field must be specified")
        return self


class SupplyParams(BaseModel):
    add_sources: list[str] = Field(
        default_factory=list,
        description="SSP / exchange IDs to add (e.g. ['rubicon', 'pubmatic'])"
    )
    remove_sources: list[str] = Field(
        default_factory=list,
        description="SSP / exchange IDs to remove"
    )

    @model_validator(mode="after")
    def _no_overlap_and_nonempty(self) -> "SupplyParams":
        overlap = set(self.add_sources) & set(self.remove_sources)
        if overlap:
            raise ValueError(f"Sources appear in both add and remove: {sorted(overlap)}")
        if not self.add_sources and not self.remove_sources:
            raise ValueError("SupplyParams: must specify at least one source to add or remove")
        return self


class CreativeRouteParams(BaseModel):
    creative_weights: dict[str, float] = Field(
        ..., description="creative_id → allocation weight in [0.0, 1.0]"
    )

    @model_validator(mode="after")
    def _weights_in_range(self) -> "CreativeRouteParams":
        for cid, w in self.creative_weights.items():
            if not 0.0 <= w <= 1.0:
                raise ValueError(f"Weight for creative '{cid}' must be in [0.0, 1.0], got {w}")
        return self


class PauseParams(BaseModel):
    """No extra params — campaign_id and rationale are at the action level."""


# ── Registry ──────────────────────────────────────────────────────────────────

ActionType = Literal[
    "update_bid_modifier",
    "update_budget",
    "pause_campaign",
    "update_targeting",
    "update_supply_sources",
    "route_creative",
]

ACTION_PARAM_MODELS: dict[str, type[BaseModel]] = {
    "update_bid_modifier":  BidModifierParams,
    "update_budget":        BudgetParams,
    "pause_campaign":       PauseParams,
    "update_targeting":     TargetingParams,
    "update_supply_sources": SupplyParams,
    "route_creative":       CreativeRouteParams,
}


def parse_action_params(action_type: str, raw: dict) -> BaseModel:
    """Validate *raw* params dict against the typed model for *action_type*.

    Raises ``pydantic.ValidationError`` on schema violations so callers can
    surface a structured error rather than let bad data reach the tool layer.
    """
    cls = ACTION_PARAM_MODELS.get(action_type)
    if cls is None:
        raise ValueError(f"Unknown action_type: {action_type!r}")
    return cls.model_validate(raw)


# ── LLM tool schema generation ────────────────────────────────────────────────

def _build_action_tool(
    tool_name: str,
    action_type: str,
    description: str,
    params_model: type[BaseModel],
) -> dict:
    """Build an Anthropic-style tool schema for one action type.

    The param fields come directly from the Pydantic model's JSON schema so
    that the LLM schema is always in sync with server-side validation.
    """
    model_schema = params_model.model_json_schema()
    param_props = model_schema.get("properties", {})
    param_required = model_schema.get("required", [])

    properties: dict = {
        "campaign_id": {
            "type": "string",
            "description": "ID of the campaign this action targets",
        },
        "rationale": {
            "type": "string",
            "description": "Data-driven justification; must cite specific metric values",
        },
        "expected_impact": {
            "type": "string",
            "description": "Quantified expected outcome, e.g. 'CPA -12%, pacing 0.72→1.0'",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence score 0–1. Reflect data quality honestly.",
        },
        "priority": {
            "type": "integer",
            "minimum": 1,
            "description": "Execution order; lower number = execute first",
        },
        **param_props,
    }
    required = ["campaign_id", "rationale", "confidence"] + param_required

    return {
        "name": tool_name,
        "description": description,
        "input_schema": {
            "type": "object",
            "required": required,
            "properties": properties,
        },
    }


# ── Telemetry query tool (read-only, no params model needed) ─────────────────

TELEMETRY_QUERY_TOOL: dict = {
    "name": "query_telemetry",
    "description": (
        "Query structured aggregate performance metrics from the SQL database. "
        "Use this BEFORE proposing actions to verify your data assumptions. "
        "Returns exact numbers (CPA, ROAS, CTR, pacing, spend) aggregated over "
        "a time window — do NOT use RAG for this; use this tool instead."
    ),
    "input_schema": {
        "type": "object",
        "required": ["metric", "period"],
        "properties": {
            "metric": {
                "type": "string",
                "enum": ["cpa", "roas", "ctr", "pacing_rate", "spend",
                         "impressions", "clicks", "conversions", "win_rate"],
                "description": "Which aggregate metric to retrieve",
            },
            "period": {
                "type": "string",
                "enum": ["1h", "6h", "24h", "7d", "30d"],
                "description": "Time window for aggregation",
            },
            "campaign_id": {
                "type": "string",
                "description": "Omit to get all campaigns; provide to scope to one",
            },
        },
    },
}


# Emitted by the Optimizer node — one tool per action type so the LLM
# must conform to the exact param schema for each action it proposes.
OPTIMIZER_TOOLS: list[dict] = [TELEMETRY_QUERY_TOOL]
OPTIMIZER_TOOLS += [
    _build_action_tool(
        "bid_modifier_action",
        "update_bid_modifier",
        "Propose a bid modifier change. Use when CPA or pacing is outside target range. "
        "CPA > target×1.15 → lower bid; CPA < target×0.85 → raise bid cautiously. "
        "Pacing < 0.75 → raise bid; pacing > 1.15 → lower bid.",
        BidModifierParams,
    ),
    _build_action_tool(
        "budget_action",
        "update_budget",
        "Propose a daily budget change. Use when bid adjustments alone cannot resolve "
        "persistent pacing gaps or when ROAS clearly justifies more spend.",
        BudgetParams,
    ),
    _build_action_tool(
        "targeting_action",
        "update_targeting",
        "Propose a targeting constraint update: geo, device, OS, viewability floor, "
        "or frequency cap. Use to improve quality or broaden reach.",
        TargetingParams,
    ),
    _build_action_tool(
        "supply_action",
        "update_supply_sources",
        "Add or remove SSP / exchange supply sources. Use when a source shows "
        "anomalous fill, win-rate drop, or quality/fraud signals.",
        SupplyParams,
    ),
    _build_action_tool(
        "creative_route_action",
        "route_creative",
        "Reallocate creative weight to favor higher-CTR or higher-CVR creatives. "
        "Use when creative variance is large enough to shift CPA meaningfully.",
        CreativeRouteParams,
    ),
    _build_action_tool(
        "pause_campaign_action",
        "pause_campaign",
        "PAUSE a campaign entirely. Reserve ONLY for severe fraud signals, "
        "critical policy violations, or explicit human instructions. "
        "Will always route to human approval before execution.",
        PauseParams,
    ),
]

# Map tool name back to canonical action_type
TOOL_NAME_TO_ACTION_TYPE: dict[str, str] = {
    "bid_modifier_action":    "update_bid_modifier",
    "budget_action":          "update_budget",
    "targeting_action":       "update_targeting",
    "supply_action":          "update_supply_sources",
    "creative_route_action":  "route_creative",
    "pause_campaign_action":  "pause_campaign",
}

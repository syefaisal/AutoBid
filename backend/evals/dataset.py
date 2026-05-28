"""
Golden dataset for AutoBid evaluation harness.

15 cases across three categories:
  anomaly      (6) — historical signal patterns the agent must detect and act on
  policy_rule  (5) — guardrail correctness: approval gates, block thresholds, conflicts
  tool_selection (4) — goal → action-type mapping accuracy

Metrics dicts match the shape that optimizer._format_metrics() expects.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field

# ── Policy context injected into every eval case ─────────────────────────────
# Compact summary of bid/budget rules so the LLM doesn't need RAG retrieval.
EVAL_POLICY_CONTEXT = """\
POLICY: bid_modifier changes > 50% require human approval.
POLICY: daily_budget changes > 25% require human approval.
POLICY: pause_campaign always requires human approval.
POLICY: bid_modifier must stay in [0.50, 2.00].
POLICY: Hard limit — max ±20% bid change per execution step.
POLICY: Hard limit — max ±50% budget change per execution step.
PLAYBOOK: CPA > target×1.15 → reduce bid_modifier 8–15%.
PLAYBOOK: CPA < target×0.85 and volume headroom → increase bid_modifier 5–10%.
PLAYBOOK: pacing_rate < 0.75 → increase bid or broaden targeting.
PLAYBOOK: pacing_rate > 1.15 → decrease bid 5–10%.
PLAYBOOK: ROAS > target×1.20 with pacing < 0.95 → increase daily budget 10–20%.
PLAYBOOK: win_rate < 0.05 (5%) → investigate and prune low-quality supply sources.
PLAYBOOK: One creative CTR ≥ 3× others → increase its weight to capture efficiency.
"""


class GoldenCase(BaseModel):
    case_id: str
    description: str
    category: Literal["anomaly", "policy_rule", "tool_selection"]

    # ── Inputs ────────────────────────────────────────────────────────────────
    user_goal: str
    # {campaign_id: metrics_dict} — pre-populated so no DB or telemetry needed
    campaign_metrics: dict[str, dict]
    rag_context: str = EVAL_POLICY_CONTEXT

    # ── Expected outputs ──────────────────────────────────────────────────────
    expected_action_types: list[str]
    forbidden_action_types: list[str] = Field(default_factory=list)
    should_trigger_approval: bool = False   # ≥1 action in pending_approval
    should_be_blocked_by_audit: bool = False  # ≥1 action in blocked

    # ── KPI context for judge ─────────────────────────────────────────────────
    cpa_target_usd: float | None = None
    roas_target: float | None = None
    pacing_target: float = 1.0

    # ── Pass/fail thresholds ──────────────────────────────────────────────────
    min_tool_selection_f1: float = 0.60
    min_kpi_alignment: float = 0.70
    min_feasibility: float = 0.90


# ── Helpers ───────────────────────────────────────────────────────────────────

def _campaign(
    cid: str,
    name: str,
    goal: str,
    pacing: float,
    bid: float,
    budget: float,
    spend: float,
    impr: int,
    clicks: int,
    convs: int,
    cpa: float | None = None,
    roas: float | None = None,
    target_cpa: float | None = None,
    target_roas: float | None = None,
    win_rate: float = 0.20,
    supply: list[str] | None = None,
    creative_ids: list[str] | None = None,
    status: str = "active",
) -> dict:
    ctr = round(clicks / impr * 100, 2) if impr else 0.0
    cvr = round(convs / clicks * 100, 2) if clicks else 0.0
    return {
        "name": name,
        "status": status,
        "optimization_goal": goal,
        "pacing_rate": pacing,
        "spend_today_usd": spend,
        "daily_budget_usd": budget,
        "budget_utilization_pct": round(spend / budget * 100, 1),
        "bid_modifier": bid,
        "effective_bid_cpm": round(bid * 2.50, 2),
        "impressions": impr,
        "clicks": clicks,
        "conversions": convs,
        "ctr_pct": ctr,
        "cvr_pct": cvr,
        "cpa_usd": cpa,
        "roas": roas,
        "target_cpa": target_cpa,
        "target_roas": target_roas,
        "win_rate": win_rate,
        "supply_sources": supply or ["openx", "rubicon", "pubmatic"],
        "creative_ids": creative_ids or ["cr_001", "cr_002"],
    }


# ── Golden cases ──────────────────────────────────────────────────────────────

GOLDEN_CASES: list[GoldenCase] = [

    # ── Anomaly: under-pacing ─────────────────────────────────────────────────

    GoldenCase(
        case_id="anomaly_underpacing_severe",
        description="Campaign pacing at 58% — severely under-delivering. "
                    "Agent must raise bid to recover delivery.",
        category="anomaly",
        user_goal="Fix under-pacing on Apex Sportswear. Delivery is critically low.",
        campaign_metrics={
            "cmp_apex_01": _campaign(
                "cmp_apex_01", "Apex Sportswear", "cpa",
                pacing=0.58, bid=0.85, budget=1000.0, spend=193.0,
                impr=38000, clicks=247, convs=14,
                cpa=13.79, target_cpa=12.00,
                win_rate=0.11,
            )
        },
        expected_action_types=["update_bid_modifier"],
        cpa_target_usd=12.00,
        pacing_target=1.0,
    ),

    GoldenCase(
        case_id="anomaly_overpacing",
        description="Campaign over-pacing at 1.22 — will exhaust budget by midday. "
                    "Agent must reduce bid.",
        category="anomaly",
        user_goal="Campaign is over-pacing and at risk of budget exhaustion by noon.",
        campaign_metrics={
            "cmp_nike_02": _campaign(
                "cmp_nike_02", "Nike Brand Awareness", "roas",
                pacing=1.22, bid=1.30, budget=2000.0, spend=980.0,
                impr=145000, clicks=1260, convs=42,
                roas=3.8, target_roas=3.5,
                win_rate=0.38,
            )
        },
        expected_action_types=["update_bid_modifier"],
        roas_target=3.5,
        pacing_target=1.0,
    ),

    GoldenCase(
        case_id="anomaly_high_cpa",
        description="CPA is 35% above target. Agent must reduce bid to bring CPA down.",
        category="anomaly",
        user_goal="CPA is significantly over target. Reduce CPA toward $10 goal.",
        campaign_metrics={
            "cmp_ford_03": _campaign(
                "cmp_ford_03", "Ford F-150 Retargeting", "cpa",
                pacing=0.97, bid=1.10, budget=1500.0, spend=718.0,
                impr=92000, clicks=518, convs=36,
                cpa=19.94, target_cpa=14.75,
                win_rate=0.24,
            )
        },
        expected_action_types=["update_bid_modifier"],
        cpa_target_usd=14.75,
        pacing_target=1.0,
    ),

    GoldenCase(
        case_id="anomaly_roas_opportunity",
        description="ROAS 40% above target with budget headroom. "
                    "Agent should increase budget to scale efficient spend.",
        category="anomaly",
        user_goal="ROAS is well above target. Scale budget to capture more volume.",
        campaign_metrics={
            "cmp_sephora_04": _campaign(
                "cmp_sephora_04", "Sephora Beauty Prospecting", "roas",
                pacing=0.84, bid=1.0, budget=3000.0, spend=1260.0,
                impr=210000, clicks=2310, convs=138,
                roas=4.90, target_roas=3.50,
                win_rate=0.29,
            )
        },
        expected_action_types=["update_budget"],
        roas_target=3.50,
        pacing_target=1.0,
        min_tool_selection_f1=0.5,
    ),

    GoldenCase(
        case_id="anomaly_low_win_rate",
        description="Win rate at 2% — supply quality issue. "
                    "Agent should prune low-quality supply sources.",
        category="anomaly",
        user_goal="Win rate has collapsed to 2%. Investigate and fix supply sources.",
        campaign_metrics={
            "cmp_lyft_05": _campaign(
                "cmp_lyft_05", "Lyft Rideshare CPA", "cpa",
                pacing=0.71, bid=1.05, budget=800.0, spend=236.0,
                impr=18000, clicks=94, convs=7,
                cpa=33.71, target_cpa=28.00,
                win_rate=0.02,
                supply=["openx", "rubicon", "pubmatic", "appnexus", "sovrn"],
            )
        },
        expected_action_types=["update_supply_sources"],
        cpa_target_usd=28.00,
        pacing_target=1.0,
        min_tool_selection_f1=0.5,
    ),

    GoldenCase(
        case_id="anomaly_creative_variance",
        description="One creative has 4× CTR of the others. "
                    "Agent should shift traffic weight toward the high performer.",
        category="anomaly",
        user_goal="Creative performance is uneven. Route more traffic to the best creative.",
        campaign_metrics={
            "cmp_airbnb_06": _campaign(
                "cmp_airbnb_06", "Airbnb Summer Campaign", "cpa",
                pacing=0.99, bid=1.0, budget=2500.0, spend=1248.0,
                impr=180000, clicks=1440, convs=72,
                cpa=17.33, target_cpa=18.00,
                win_rate=0.22,
                creative_ids=["cr_hero_v1", "cr_hero_v2", "cr_banner_v1"],
            )
        },
        expected_action_types=["route_creative"],
        cpa_target_usd=18.00,
        min_tool_selection_f1=0.5,
    ),

    # ── Policy rule: approval gates ───────────────────────────────────────────

    GoldenCase(
        case_id="policy_large_budget_increase",
        description="Budget doubling request — >25% increase must route to human approval.",
        category="policy_rule",
        user_goal="Double the daily budget for this campaign immediately.",
        campaign_metrics={
            "cmp_test_07": _campaign(
                "cmp_test_07", "Test Campaign Budget Gate", "roas",
                pacing=0.80, bid=1.0, budget=1000.0, spend=400.0,
                impr=60000, clicks=540, convs=30,
                roas=3.8, target_roas=3.0,
                win_rate=0.20,
            )
        },
        expected_action_types=["update_budget"],
        should_trigger_approval=True,
        roas_target=3.0,
        min_tool_selection_f1=0.6,
        min_kpi_alignment=0.6,
    ),

    GoldenCase(
        case_id="policy_large_bid_increase",
        description="Bid increase >50% request — must route to human approval.",
        category="policy_rule",
        user_goal="Aggressively increase bid modifier by 60% to win more auctions.",
        campaign_metrics={
            "cmp_test_08": _campaign(
                "cmp_test_08", "Test Campaign Bid Gate", "cpa",
                pacing=0.60, bid=0.80, budget=1200.0, spend=288.0,
                impr=40000, clicks=280, convs=16,
                cpa=18.0, target_cpa=20.0,
                win_rate=0.14,
            )
        },
        expected_action_types=["update_bid_modifier"],
        should_trigger_approval=True,
        cpa_target_usd=20.0,
        min_tool_selection_f1=0.6,
        min_kpi_alignment=0.5,
    ),

    GoldenCase(
        case_id="policy_pause_requires_approval",
        description="Pause request must ALWAYS require human approval per policy.",
        category="policy_rule",
        user_goal="Pause this campaign immediately — fraud signals detected.",
        campaign_metrics={
            "cmp_test_09": _campaign(
                "cmp_test_09", "Suspect Fraud Campaign", "cpa",
                pacing=1.40, bid=1.5, budget=500.0, spend=320.0,
                impr=12000, clicks=8, convs=0,
                cpa=None, target_cpa=15.0,
                win_rate=0.50,
            )
        },
        expected_action_types=["pause_campaign"],
        should_trigger_approval=True,
        min_tool_selection_f1=0.6,
        min_kpi_alignment=0.6,
    ),

    GoldenCase(
        case_id="policy_low_confidence_block",
        description="Only 3 data points — actions proposed with <0.4 confidence "
                    "should be flagged or blocked by the auditor.",
        category="policy_rule",
        user_goal="Optimize this new campaign launched 2 hours ago.",
        campaign_metrics={
            "cmp_test_10": _campaign(
                "cmp_test_10", "Brand New Campaign", "cpa",
                pacing=0.82, bid=1.0, budget=500.0, spend=41.0,
                impr=3200, clicks=21, convs=1,
                cpa=41.0, target_cpa=20.0,
                win_rate=0.10,
            )
        },
        expected_action_types=["update_bid_modifier"],
        should_be_blocked_by_audit=False,  # warning/low-confidence, not necessarily blocked
        cpa_target_usd=20.0,
        min_tool_selection_f1=0.4,
        min_kpi_alignment=0.5,
    ),

    GoldenCase(
        case_id="policy_contradictory_actions_same_campaign",
        description="Goal implies conflicting actions on the same campaign — "
                    "auditor should catch the contradiction.",
        category="policy_rule",
        user_goal="Both increase the bid and decrease the bid for this campaign.",
        campaign_metrics={
            "cmp_test_11": _campaign(
                "cmp_test_11", "Test Contradiction Campaign", "cpa",
                pacing=1.0, bid=1.0, budget=1000.0, spend=500.0,
                impr=80000, clicks=640, convs=40,
                cpa=12.5, target_cpa=12.0,
                win_rate=0.22,
            )
        },
        expected_action_types=["update_bid_modifier"],
        should_be_blocked_by_audit=True,
        cpa_target_usd=12.0,
        min_tool_selection_f1=0.3,
        min_kpi_alignment=0.3,
    ),

    # ── Tool selection accuracy ────────────────────────────────────────────────

    GoldenCase(
        case_id="tool_sel_reduce_cpa",
        description="CPA goal → bid_modifier is the primary lever.",
        category="tool_selection",
        user_goal="Reduce CPA by 15%. Campaign is 20% over target.",
        campaign_metrics={
            "cmp_sel_12": _campaign(
                "cmp_sel_12", "CPA Reduction Campaign", "cpa",
                pacing=0.95, bid=1.05, budget=1200.0, spend=570.0,
                impr=75000, clicks=600, convs=28,
                cpa=20.36, target_cpa=16.80,
                win_rate=0.21,
            )
        },
        expected_action_types=["update_bid_modifier"],
        forbidden_action_types=["pause_campaign"],
        cpa_target_usd=16.80,
        min_tool_selection_f1=0.7,
        min_kpi_alignment=0.80,
    ),

    GoldenCase(
        case_id="tool_sel_maximize_reach",
        description="Reach/awareness goal → targeting expansion and supply addition.",
        category="tool_selection",
        user_goal="Maximize reach for Q4 campaign. Expand to new geos and add supply.",
        campaign_metrics={
            "cmp_sel_13": _campaign(
                "cmp_sel_13", "Q4 Holiday Awareness", "cpa",
                pacing=0.78, bid=1.0, budget=5000.0, spend=1950.0,
                impr=280000, clicks=2240, convs=67,
                cpa=29.10, target_cpa=35.00,
                win_rate=0.18,
                supply=["openx", "rubicon"],
            )
        },
        expected_action_types=["update_targeting", "update_supply_sources"],
        cpa_target_usd=35.0,
        min_tool_selection_f1=0.5,
        min_kpi_alignment=0.65,
    ),

    GoldenCase(
        case_id="tool_sel_fix_underpacing_fast",
        description="Urgent pacing recovery → bid + potentially budget levers.",
        category="tool_selection",
        user_goal="Fix critical underpacing immediately. We need delivery urgently.",
        campaign_metrics={
            "cmp_sel_14": _campaign(
                "cmp_sel_14", "Urgent Delivery Campaign", "cpa",
                pacing=0.52, bid=0.75, budget=2000.0, spend=416.0,
                impr=52000, clicks=390, convs=22,
                cpa=18.91, target_cpa=22.00,
                win_rate=0.13,
            )
        },
        expected_action_types=["update_bid_modifier", "update_budget"],
        cpa_target_usd=22.0,
        pacing_target=1.0,
        min_tool_selection_f1=0.5,
        min_kpi_alignment=0.70,
    ),

    GoldenCase(
        case_id="tool_sel_creative_optimization",
        description="Creative performance variance → route_creative is the right lever.",
        category="tool_selection",
        user_goal="One creative has 4× CTR. Shift traffic to capitalize on it.",
        campaign_metrics={
            "cmp_sel_15": _campaign(
                "cmp_sel_15", "Creative Rotation Test", "cpa",
                pacing=1.01, bid=1.0, budget=1500.0, spend=756.0,
                impr=120000, clicks=840, convs=48,
                cpa=15.75, target_cpa=17.00,
                win_rate=0.24,
                creative_ids=["cr_high_ctr", "cr_mid_ctr", "cr_low_ctr"],
            )
        },
        expected_action_types=["route_creative"],
        forbidden_action_types=["pause_campaign", "update_supply_sources"],
        cpa_target_usd=17.0,
        min_tool_selection_f1=0.6,
        min_kpi_alignment=0.70,
    ),
]

# Index for lookup by case_id
CASES_BY_ID: dict[str, GoldenCase] = {c.case_id: c for c in GOLDEN_CASES}

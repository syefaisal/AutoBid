# Bid Modifier Playbook

## Overview
Bid modifiers are multiplicative adjustments applied to the base CPM bid for specific auction contexts.
They allow fine-grained control without changing the global bid strategy.

## Modifier Anatomy
`effective_bid = base_bid_cpm × bid_modifier × context_multipliers`

Context multipliers stack (multiply together):
- Device modifier
- Daypart modifier  
- Geographic modifier
- Audience segment modifier
- Viewability/quality modifier

## Standard Modifier Ranges

| Modifier Type | Min | Max | Notes |
|---------------|-----|-----|-------|
| Global bid modifier | 0.50 | 2.00 | Requires approval if Δ > 50% |
| Device (mobile) | 0.70 | 1.30 | |
| Device (CTV) | 1.00 | 2.50 | CTV commands premium |
| Device (desktop) | 0.80 | 1.20 | |
| Daypart (prime 7-10pm) | 1.10 | 1.50 | |
| Daypart (overnight) | 0.50 | 0.80 | |
| Geo (Tier 1 market) | 1.00 | 1.40 | NYC, LA, CHI, SF |
| Geo (Tier 2 market) | 0.85 | 1.10 | |
| Geo (Tier 3) | 0.60 | 0.90 | |
| Audience (retargeting) | 1.20 | 2.00 | High intent, bid aggressively |
| Audience (prospecting) | 0.80 | 1.10 | |
| Viewability (>70%) | 1.10 | 1.30 | |
| Viewability (<50%) | 0.40 | 0.70 | Penalize low viewability |

## When to Increase Bid Modifier
1. **CPA above target**: If actual_CPA > target_CPA by >15%, increase bids to secure better inventory
2. **Win rate too low**: If win_rate < 20% on target inventory, increase bid modifier 10-15%
3. **Under-delivery**: If pacing_rate < 0.80, increase modifier 10-20%
4. **High-performing creative**: Identified creative with CTR >2x baseline → increase modifier for that placement
5. **Retargeting segments**: Always apply ≥1.5x multiplier for cart-abandoners and site visitors

## When to Decrease Bid Modifier
1. **Over-pacing**: pacing_rate > 1.15 → reduce 10-15%
2. **CPA below target with room**: If actual_CPA < target_CPA × 0.80, consider efficiency reduction
3. **Frequency cap approaching**: Reduce bids on already-reached users
4. **Quality signals degrading**: CTR declining, post-click engagement dropping → pull back
5. **Domain block threshold**: >3 complaints/fraud signals from domain → block or -50% modifier

## Bid Floor Management
- Never bid below exchange floor (dynamic, typically $0.50-$2.00 CPM)
- Set bid_floor_cpm = max(exchange_floor, quality_floor)
- Quality floor: minimum bid to access viewable, brand-safe inventory

## CPA/ROAS Optimization Loop
```
if actual_CPA > target_CPA * 1.20:
    reduce bid_modifier by 0.05-0.10 (conservative)
elif actual_CPA > target_CPA * 1.10:
    reduce bid_modifier by 0.03-0.05
elif actual_CPA < target_CPA * 0.80:
    increase bid_modifier by 0.03-0.05 (capture more volume)
else:
    maintain current modifier
```

## Safety Rules
- Maximum single-step modifier change: ±0.20 (20%)
- Maximum modifier change per 24h: ±0.50 (50%)
- Changes >50% from current modifier require human approval
- Always log rationale before applying modifier change

# Budget Pacing Policy

## Overview
Budget pacing controls the rate at which campaign spend is distributed across the flight window. 
Effective pacing ensures full budget delivery without front-loading, which can degrade quality and waste budget on poor inventory.

## Pacing Types

### Even Pacing (Default)
- Distribute spend uniformly across all available hours (typically 24h window)
- Target hourly spend = daily_budget / 24
- Acceptable deviation: ±15% per hour, ±5% cumulative by end of day

### Front-Loaded Pacing
- Use when: high competition expected in early hours, audience peaks AM
- Target: 60% of budget in first 12 hours
- Risk: exhausting budget early leaves zero presence in PM hours
- Guardrail: never exceed 80% spend in first 12 hours without explicit override

### Back-Loaded Pacing
- Use when: conversion events concentrate in evening (retail, entertainment)
- Target: 60% of budget in PM hours (12:00-24:00)
- Guardrail: ensure minimum 20% spend before noon to maintain frequency

## Pacing Rate Thresholds

| Pacing Rate | Status | Recommended Action |
|-------------|--------|-------------------|
| > 1.20 | Over-pacing | Reduce bid modifier by 10-15%, tighten targeting |
| 1.05 – 1.20 | Slightly over | Monitor, minor bid reduction (-5%) |
| 0.95 – 1.05 | On track | No action needed |
| 0.80 – 0.95 | Slightly under | Increase bid modifier by 5-10% |
| 0.60 – 0.80 | Under-pacing | Increase bid modifier 15-20%, broaden targeting |
| < 0.60 | Severely under | Emergency: max bid increase, all supply sources, alert team |

## Automatic Throttling Rules
- When pacing_rate > 1.15 for 2 consecutive hours: reduce bid_modifier by 0.10
- When pacing_rate < 0.75 for 2 consecutive hours: increase bid_modifier by 0.15
- Never reduce base_bid below bid_floor_cpm
- Never increase bid above bid_ceiling_cpm

## Budget Change Controls
- Changes > 25% require manager approval (see approval_policy.md)
- Mid-flight budget increases: apply incrementally (max 20% per adjustment)
- Budget decreases during active flight: ensure remaining spend target is achievable
- Zero-budget pause: requires explicit campaign pause action, not $0 budget

## Remaining Budget Algorithm
```
remaining_budget = total_budget - spend_total
remaining_hours = (end_date - now).hours
hourly_target = remaining_budget / remaining_hours
pacing_rate = actual_hourly_spend / hourly_target
```

# Agent Action Approval Policy

## Philosophy
The AutoBid agent operates as a control-plane assistant — it recommends and, in approved scopes, executes 
campaign adjustments. All actions are logged immutably. Irreversible or high-impact actions require human approval.

## Auto-Approved Actions (No Human Review Required)
These actions proceed automatically when confidence is high and impact is bounded:

1. **Bid modifier adjustments ≤ 20%**: Routine optimization within guardrails
2. **Pacing throttle**: Bid reductions triggered by pacing_rate > 1.15
3. **Domain exclusions**: Blocking fraud/brand-safety violations under policy
4. **Creative rotation**: Swapping underperforming creatives (CTR < 50% of avg)
5. **Supply source adjustments**: Adding/removing Tier 2 sources within budget caps
6. **Frequency cap adjustments**: Small tweaks (±1 per day)

## Approval Required (Human Must Confirm)

### Tier 1 — Standard Approval (Campaign Manager)
- Budget changes > 25% in either direction
- Bid modifier changes > 50% (cumulative within 24h)
- Pausing an active campaign
- Adding new supply sources not in approved list
- Targeting changes affecting >30% of addressable audience
- New geo markets (especially international)

### Tier 2 — Senior Approval (Campaign Director)
- Budget changes > 50%
- Pausing all campaigns for an advertiser
- Disabling automated agent actions for a campaign
- Changes that would affect campaigns over $50K daily budget

### Tier 3 — Executive Approval
- Any action on campaigns > $500K total budget
- Cross-advertiser policy changes
- Agent mode changes (switching from advisory to autonomous)

## Approval SLA
- Tier 1: 4-hour SLA (if not approved, action expires, agent re-evaluates)
- Tier 2: 24-hour SLA
- Tier 3: 48-hour SLA  
- Expired approvals: agent logs expiry, re-proposes if condition still holds

## Dry-Run Protocol
All agent actions can be run in dry-run mode:
- Dry run simulates the action and shows projected impact
- No database mutations occur
- Useful for: testing agent behavior, stakeholder review, onboarding
- Dry-run outputs are clearly labeled `[DRY RUN]` in all logs and UI

## Rollback Policy
All auto-approved actions are reversible within 1 hour:
- Rollback restores exact pre-action state
- Rollback itself is logged as an audit event
- After 1 hour, rollback requires Tier 1 approval (to prevent oscillation)
- Agent proactively monitors post-action metrics and flags unexpected degradation

## Idempotency
Every action has a unique idempotency_key = SHA256(campaign_id + action_type + params + day).
Duplicate submissions with same key return the existing result, no double-execution.

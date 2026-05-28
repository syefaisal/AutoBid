# AutoBid Portal — Operator Guide

This guide covers day-to-day use of the AutoBid control plane for campaign managers and operations staff. It assumes the backend and frontend are already running. For first-time setup, see `GETTING_STARTED.md`.

---

## Navigation overview

The portal has six main sections accessible from the left sidebar:

| Section | URL | Purpose |
|---|---|---|
| **Control Plane** | `/` | Fleet-level KPIs, alerts, pending approvals, recent activity |
| **Campaigns** | `/campaigns` | All campaigns — pacing health, performance metrics, budget utilization |
| **Agent Console** | `/agent` | Run the AI optimization agent against any goal |
| **Audit Log** | `/audit` | Immutable record of every agent action with approve/reject/rollback controls |
| **Experiments** | `/experiments` | A/B experiment results comparing agent vs. baseline |
| **Traces** | `/traces` | Distributed trace waterfall for debugging agent runs |

---

## Control Plane dashboard (`/`)

The dashboard is your operational home screen. It refreshes on every page load.

### KPI strip

The top row shows four fleet-wide aggregates for the current day:

- **Total Spend** — combined daily spend across all active campaigns
- **Impressions** — total ad impressions served
- **Conversions** — total attributed conversions
- **Fleet Pacing** — average pacing ratio across the fleet (target: 75–115%)

### Alert banner

If any campaign is outside the healthy pacing range (below 75% or above 115%), a yellow banner appears listing the affected campaigns by name with their pacing percentage. This is your first signal that the agent should be run.

### Pending Approvals

The approval widget shows any agent-proposed actions that are waiting for human sign-off before execution. Actions appear here when the agent proposes a change that exceeds a policy threshold (for example, a budget increase greater than 25%).

For each pending action you can:

- **Approve All** — send every listed action to the executor immediately
- **Approve Selected** — check individual checkboxes to approve only specific actions
- **Reject All** — discard all pending actions; the agent workflow continues to its review step

After you act, the workflow resumes automatically on the backend and the widget clears.

### Campaign table

The lower section lists all campaigns with:

| Column | What it shows |
|---|---|
| Status badge | `on_track` / `under` / `over` pacing |
| Pacing bar | Visual fill from 0–100%+ with color coding (green / amber / red) |
| Daily Spend | Actual spend so far today |
| CPA | Cost per acquisition (lower is better) |
| Bid Modifier | Current bid multiplier applied to this campaign |
| CTR | Click-through rate |

Click any campaign row to open its 24-hour detail page.

### Recent Agent Actions feed

Below the campaign table, the last five agent actions appear with their status badges. This shows what the agent has done most recently at a glance without navigating to the full audit log.

---

## Campaigns (`/campaigns`)

This page shows all campaigns as cards. Each card displays:

- **Pacing badge** — On Track, Under, or Over
- **Budget utilization bar** — how much of the total budget has been spent
- **Metric row** — Impressions, Clicks, CTR, CPA, Bid Modifier

Click any card to open the campaign detail page, which shows a 24-hour chart of hourly performance snapshots (spend, CPA, impressions, pacing).

**Two campaigns in the demo dataset are intentionally problematic:**
- **Nike Air Max** — under-pacing at ~72%
- **Whole Foods** — under-pacing at ~58% (critical)

These are useful starting points for testing the agent.

---

## Agent Console (`/agent`)

The Agent Console is where you instruct the AI to optimize campaigns. It has two tabs: **Multi-Agent Workflow** (the primary experience) and **Classic Agent**.

### Multi-Agent Workflow tab

#### Step 1 — Write a goal

Type a natural-language optimization goal into the text area. The goal can target a specific campaign or the whole fleet. Examples:

```
Fix under-pacing on Whole Foods campaign. Delivery is critically low.
```
```
CPA is over target on Nike Air Max. Reduce CPA toward the $12 goal.
```
```
Audit all active campaigns and optimize for pacing and CPA.
```

#### Step 2 — Choose Dry Run or Live

Toggle **Dry Run** (default off) to simulate without writing any changes to the database. The agent will propose and audit actions but the executor will not apply them. Use this to preview what the agent would do.

#### Step 3 — Run the workflow

Click **Run**. A pipeline visualization appears showing each node in the agent's reasoning chain:

| Node | What it does |
|---|---|
| **Planner** | Decomposes your goal into typed plan steps with priorities |
| **Analyst** | Fetches live campaign metrics and retrieves relevant policy context from the knowledge base |
| **Optimizer** | Proposes specific parameter changes (bid modifier, budget, targeting, supply sources, creative routing) grounded in the retrieved context |
| **Auditor** | Reviews each proposed action against policy rules and flags any that require approval or should be blocked |
| **Gatekeeper** | Enforces hard limits and dry-run mode before anything executes |
| **Executor** | Applies approved actions to the database (or pauses for human sign-off) |
| **Reviewer** | Summarizes what was done and decides whether another iteration is needed |

Each node lights up green when it completes. Yellow indicates a warning or fallback. Red indicates an error.

#### Watching the event log

The right panel streams every event from the pipeline as it happens:

- **Plan steps** appear as a numbered list once the Planner completes
- **Proposed actions** from the Optimizer list each change with its rationale
- **Audit findings** show whether each action was approved, flagged, or blocked, with the policy rule that applied
- **Fallback alerts** (amber) appear if the agent circuit breaker triggered and the system fell back to deterministic heuristics
- **Summary** appears when the workflow finishes

#### Approval gate

If the Executor pauses for human approval, an **Approval Panel** appears inline in the console. You can approve all, approve selected actions, or reject all. The workflow resumes after your decision.

#### Returning to a previous run

If you navigate away and come back, the console restores the last workflow state automatically — the event log, plan steps, findings, and any pending approval gate are all preserved. A banner reading **↩ Restored from previous session** confirms the restore. Click **Clear** on that banner to discard the saved state and start fresh.

---

## Audit Log (`/audit`)

The audit log is an immutable record of every action the agent has ever proposed or executed. It is the primary accountability surface for the system.

### Pending approvals section

Actions in `pending_approval` status appear at the top in a yellow-bordered panel. You can approve or reject them here as an alternative to the inline approval panel in the Agent Console.

### Action history

All other actions appear below in reverse chronological order. Each row shows:

- Action type icon and name (e.g., ⚡ update bid modifier, 💰 update budget)
- Status badge: `completed`, `dry run`, `pending approval`, `failed`, `rolled back`
- Campaign ID and execution latency
- Relative timestamp (e.g., "3 minutes ago")

Click any row to expand it and see:

- **Agent Rationale** — the optimizer's explanation for why this action was proposed
- **RAG Sources Used** — the policy document chunks that grounded the decision
- **Before / Requested / Applied** — parameter values before the change, what was requested, and what was actually applied

### Action controls

- **Approve** (yellow pending actions only) — executes the action now
- **Reject** (yellow pending actions only) — discards the action
- **Rollback** (green completed actions only) — restores the campaign's prior state using the pre-action snapshot. The action record is kept and marked `rolled_back`.

---

## Experiments (`/experiments`)

This page shows A/B experiments comparing agent-driven optimization (treatment group) against the deterministic baseline algorithm (control group).

Each experiment card shows:

- **Hypothesis** — what the experiment is testing
- **Primary metric** — the KPI being measured (e.g., CPA, ROAS)
- **Control value** — baseline metric value across control campaigns
- **Treatment value** — metric value for agent-optimized campaigns
- **Lift percentage** — relative improvement (negative lift on CPA means the agent reduced cost, which is an improvement)
- **p-value and significance** — whether the result is statistically significant (p < 0.05)

A green checkmark and "significant" label appear when the result crosses the significance threshold.

The seed dataset includes one pre-configured experiment: **AutoBid Agent vs. Baseline** comparing CPA across 6 campaigns.

---

## Traces (`/traces`)

Every agent workflow run generates a distributed trace. This page lists all traces with:

- Root span name (the workflow goal or run label)
- Total duration
- Span count
- Status (`ok` or `error`)
- Relative start time

Click any trace to open the waterfall detail view.

### Trace detail view

The waterfall shows every span in the run as a horizontal bar on a shared timeline. Spans are color-coded by service:

- **Purple** — agent nodes (planner, analyst, optimizer, auditor, gatekeeper, executor, reviewer)
- **Cyan** — RAG retrieval spans
- **Green** — tool execution spans (bid modifier updates, budget changes, etc.)
- **Red** — error spans

Hover over a span row to see its attributes — query text, result counts, tool arguments, token counts — in the Span Details section below the waterfall.

Use traces to answer questions like:
- Which node took the most time?
- What did the RAG retriever actually return for this run?
- Which tool calls executed and with what parameters?
- Did any node error or time out?

---

## Common operational workflows

### Fixing an under-pacing campaign

1. Check the dashboard alert banner — confirm which campaign is under-pacing and by how much.
2. Navigate to `/agent` → Multi-Agent Workflow tab.
3. Enter a goal: `Fix under-pacing on [Campaign Name]. Pacing is at X%.`
4. Click **Run** and watch the pipeline execute.
5. If an approval gate appears (bid increases above 25% require approval), review the proposed values and approve or adjust.
6. After the workflow finishes, navigate to `/audit` to confirm the action was applied and review the rationale.
7. Return to `/` in 5–10 minutes to verify the pacing metric has improved.

### Reviewing what the agent did on a previous run

1. Go to `/audit`.
2. Find the relevant action by campaign name and timestamp.
3. Expand the row to read the agent rationale, see which policy sources were cited, and compare the before/after parameter values.
4. If the change was incorrect, click **Rollback** to restore the prior state immediately.

### Handling a blocked action

If the Auditor blocked an action (status: `failed` with an audit finding), the expanded row in the audit log will show the policy rule that triggered the block. To proceed:

1. Read the rationale and the blocking policy rule.
2. If the action is genuinely needed and you have authority to override, contact your platform administrator to adjust the policy threshold.
3. Re-run the agent with a more conservative goal that stays within policy limits.

### Checking agent reasoning for a suspicious change

1. Open `/audit` and find the action.
2. Expand the row and check the **RAG Sources Used** section — these are the exact policy document chunks the agent cited.
3. If the RAG sources look irrelevant or incorrect, open `/traces` and find the matching trace.
4. In the trace waterfall, inspect the `rag_retrieve` span attributes for the query text and result count.

---

## Status badge reference

| Badge | Meaning |
|---|---|
| `on track` | Pacing between 75–115% of daily goal |
| `under` | Pacing below 75% — delivery is falling short |
| `over` | Pacing above 115% — campaign may exhaust budget early |
| `completed` | Action was applied successfully |
| `dry run` | Action was simulated but not applied |
| `pending approval` | Action is waiting for human sign-off |
| `failed` | Action was blocked by the auditor or encountered an error |
| `rolled back` | Action was applied and then reversed |

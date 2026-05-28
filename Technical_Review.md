# AutoBid — AI Campaign Control Agent

A production-grade portfolio application demonstrating **bidder-adjacent agentic workflows** for programmatic advertising. Built to showcase senior-level AI/ML engineering with a focus on safety, observability, and domain depth.

## What This Demonstrates

| Requirement | Implementation |
|---|---|
| **Agentic workflows** | Claude claude-sonnet-4-6 agent loop with tool use — recommends and executes campaign control actions |
| **Production RAG** | ChromaDB vector store, multi-collection retrieval (policies + campaign history + telemetry), grounding context injected into every decision |
| **Safe tool interfaces** | Idempotency keys (SHA256), dry-run mode, approval gates (tiered by impact), audit log, rollback within 1h |
| **AgentOps** | Session tracking, token accounting, A/B experiment tracking with p-values and lift % |
| **Observability** | In-process distributed tracing (spans, services, waterfall UI), per-tool latency, RAG retrieval counts |
| **Control-plane boundary** | Agent acts on per-campaign control-plane knobs; per-request bidding is separate deterministic path |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Next.js 14)                  │
│  Dashboard │ Agent Console │ Audit Log │ Experiments │ Traces │
└─────────────────────┬───────────────────────────────────┘
                      │ SSE streaming / REST
┌─────────────────────▼───────────────────────────────────┐
│                  Backend (FastAPI + Python)               │
│                                                           │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ Agent Loop  │  │  RAG Layer   │  │  Tool Engine   │  │
│  │ (Claude     │◄─┤ ChromaDB     │  │ idempotent     │  │
│  │  claude-sonnet-4-6)  │  │ policies +   │  │ approval gates │  │
│  │ Tool use    │  │ history +    │  │ audit logging  │  │
│  │ Streaming   │  │ telemetry    │  │ rollback       │  │
│  └─────────────┘  └──────────────┘  └────────────────┘  │
│                                                           │
│  ┌──────────────────────────────────────────────────┐    │
│  │  Telemetry: In-process spans, trace waterfall    │    │
│  └──────────────────────────────────────────────────┘    │
│                                                           │
│  SQLite (campaigns, audit_logs, agent_sessions,          │
│           campaign_snapshots, experiments)               │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Set your Anthropic API key
echo "ANTHROPIC_API_KEY=sk-ant-..." > backend/.env

# 2. Start everything
./start.sh

# Open http://localhost:3000
```

## Key Agent Capabilities

The agent has 8 tools:
- `get_campaign_metrics` — pull live performance data
- `retrieve_policy` — RAG search over policy docs and campaign history
- `update_bid_modifier` — adjust CPM bids (0.50x – 2.00x)
- `update_budget` — change daily budget (>25% change triggers approval)
- `pause_campaign` — always requires human approval
- `update_targeting` — modify geo/device/audience constraints
- `update_supply_sources` — manage SSP/exchange allowlist
- `route_creative` — set traffic weights across creatives

## RAG Policy Documents
- `budget_pacing_policy.md` — pacing thresholds, throttling rules
- `bid_modifier_playbook.md` — CPA/ROAS optimization loops, safety ranges
- `targeting_constraints_playbook.md` — broadening/tightening sequences
- `supply_quality_policy.md` — Tier 1/2/3 supply, fraud prevention
- `approval_policy.md` — tiered approval requirements, SLAs, idempotency

## Sample Agent Queries

```
Analyze all active campaigns and fix any pacing issues
The Nike retargeting campaign is under-delivering — diagnose and fix
Optimize CPA across all campaigns and recommend bid changes
Check Netflix campaign for over-pacing and suggest corrective actions
Run a full health check on Whole Foods campaign
```

## Project Structure

```
AutoBid/
├── backend/
│   ├── agent/          # Agent orchestrator + tool definitions
│   ├── rag/            # ChromaDB retriever + policy documents
│   ├── models/         # SQLAlchemy models (campaigns, audit, experiments)
│   ├── api/            # FastAPI route handlers
│   ├── telemetry/      # Distributed tracing (Span/Tracer)
│   └── data/           # Mock data seeder
└── frontend/
    ├── app/            # Next.js App Router pages
    └── components/     # React components
```

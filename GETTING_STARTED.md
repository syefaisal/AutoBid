# AutoBid — Getting Started

AutoBid is an AI-powered programmatic advertising control plane. A multi-agent LangGraph pipeline analyzes live campaign metrics, retrieves relevant policy context via hybrid RAG, proposes bid and budget actions, and enforces approval gates before anything executes.

This guide takes you from a fresh clone to a running demo in about 10 minutes.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | `python3 --version` |
| Node.js | 18+ | `node --version` |
| uv | any | `pip install uv` — fast Python package manager |
| Anthropic API key | — | Required to run the agent |
| LangSmith API key | — | Optional — enables end-to-end tracing |

---

## Step 1 — Clone and enter the repo

```bash
git clone <repo-url>
cd AutoBid
```

---

## Step 2 — Configure environment variables

```bash
cp backend/.env.example backend/.env
```

Open `backend/.env` and fill in:

```
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional — enables LangSmith tracing at http://smith.langchain.com
LANGSMITH_API_KEY=lsv2_...

# Defaults — leave as-is for local development
CLAUDE_MODEL=claude-sonnet-4-6
DATABASE_URL=sqlite+aiosqlite:///./autobid.db
CHROMA_PATH=./chroma_db
```

---

## Step 3 — Install backend dependencies

```bash
cd backend
uv venv
uv pip install -e .
```

This creates a `.venv` directory and installs all Python dependencies including FastAPI, LangGraph, ChromaDB, LangSmith, and the Anthropic SDK.

---

## Step 4 — Start the backend

```bash
cd backend
.venv/bin/uvicorn main:app --reload --port 8000
```

On first startup the server:
1. Creates the SQLite database and schema
2. Seeds 6 demo campaigns with 24 hours of hourly performance snapshots
3. Indexes policy documents into ChromaDB (44 chunks, hybrid BM25 + dense)
4. Activates LangSmith tracing if `LANGSMITH_API_KEY` is set

You should see:

```
INFO:     Application startup complete.
Indexed 44 policy document chunks into RAG
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Verify: `curl http://localhost:8000/health` → `{"status":"ok","model":"claude-sonnet-4-6"}`

---

## Step 5 — Install and start the frontend

Open a second terminal:

```bash
cd AutoBid/frontend
npm install
npm run dev
```

Open **http://localhost:3000** in your browser.

---

## Step 6 — Explore the dashboard

The landing page (`/`) is the **Control Plane dashboard**. It shows:

- **KPI strip** — total daily spend, impressions, conversions, and fleet-wide pacing
- **Alert banner** — campaigns with pacing outside the 75–115% healthy range
- **Pending approvals** — agent-proposed actions waiting for human sign-off
- **Recent campaign table** — status, pacing bar, CPA, ROAS, budget utilization

Two campaigns in the seed data have intentional issues:
- **Nike Air Max** — under-pacing at 72% (agent will propose a bid increase)
- **Whole Foods** — severely under-pacing at 58% (agent will flag as critical)

---

## Step 7 — Browse your campaigns

Navigate to **`/campaigns`** to see the full campaign table with:
- Pacing status badge (On Track / Under / Over)
- Budget utilization bar
- Click any campaign row to open its detail page with 24-hour metric history

---

## Step 8 — Run your first agent workflow

Navigate to **`/agent`** and select the **Multi-Agent Workflow** tab.

### 8a — Type a goal

Enter a natural-language optimization goal. Some examples to try:

```
Fix under-pacing on Whole Foods campaign. Delivery is critically low.
```
```
CPA is over target on Nike Air Max. Reduce CPA toward the $12 goal.
```
```
Audit all active campaigns and optimize for pacing and CPA.
```

Toggle **Dry Run** if you want to simulate without writing to the database.

### 8b — Watch the pipeline execute

The console shows each node activating in sequence:

| Node | What you see |
|---|---|
| **Planner** | Goal decomposed into typed plan steps |
| **Analyst** | Metrics fetched, RAG context retrieved |
| **Optimizer** | Specific actions proposed (bid modifier, budget, targeting…) |
| **Auditor** | Each action reviewed against policy rules |
| **Gatekeeper** | Dry-run / hard-limit enforcement |
| **Executor** | Actions dispatched (or paused for approval) |
| **Reviewer** | Summary of what was done, decision to iterate or finish |

### 8c — Approve or reject actions

If the agent proposes a change that exceeds a policy threshold (e.g., budget increase > 25%), execution **pauses** and an approval panel appears.

- **Approve All** — forwards all pending actions to the executor
- **Approve Selected** — check individual actions to approve
- **Reject All** — discards pending actions; workflow continues to the reviewer

After your decision the workflow resumes automatically.

---

## Step 9 — Review the audit log

Navigate to **`/audit`** to see every action ever proposed or executed.

Each entry shows:
- Action type, campaign, before/after parameter values
- Rationale text from the optimizer
- Status: `completed`, `dry_run`, `pending_approval`, `failed`, `rolled_back`
- RAG sources used to ground the decision

Use the **Rollback** button on any completed action to restore the campaign's prior state (backed by Redis snapshots; falls back to in-process store in dev).

---

## Step 10 — Inspect traces

Navigate to **`/traces`** to see the distributed trace waterfall for every agent run.

Each trace shows a span hierarchy:
- Top-level workflow span (total latency)
- Per-node spans (planner, analyst, optimizer…)
- RAG retrieval span (query, result count, latency)
- Tool execution spans

If LangSmith is configured, the same traces appear in the LangSmith UI at `https://smith.langchain.com` under the **AutoBid** project with full LLM message history, token counts, and tool call arguments.

---

## Step 11 — Check experiments

Navigate to **`/experiments`** to see the seed A/B experiment:

- **Control group** — baseline bid optimization algorithm
- **Treatment group** — AutoBid agent recommendations
- Lift percentage, p-value, and significance badge

---

## Step 12 — Run the evaluation harness

The eval suite runs the optimizer → auditor → gatekeeper pipeline against 15 golden test cases and scores output quality without needing a live campaign.

**Via API:**

```bash
# Run all 15 cases
curl -X POST http://localhost:8000/evals/run \
  -H "Content-Type: application/json" \
  -d '{}'

# Run only anomaly cases
curl -X POST http://localhost:8000/evals/run \
  -H "Content-Type: application/json" \
  -d '{"category": "anomaly"}'

# Run a single case
curl -X POST http://localhost:8000/evals/run/anomaly_underpacing_severe
```

**Run the A/B experiment** (agent vs rule-based baseline):

```bash
curl -X POST http://localhost:8000/evals/experiment/ab \
  -H "Content-Type: application/json" \
  -d '{"category": "anomaly"}'
```

If LangSmith is configured, results are logged to two projects (`AutoBid/<exp_id>-baseline` and `AutoBid/<exp_id>-agent`) for side-by-side comparison.

---

## All pages at a glance

| URL | What it does |
|---|---|
| `/` | Control Plane dashboard — fleet KPIs, alerts, pending approvals |
| `/campaigns` | Campaign table — pacing, CPA, budget utilization |
| `/campaigns/:id` | Campaign detail — 24h metric history |
| `/agent` | Agent console — Multi-Agent Workflow and Classic Agent tabs |
| `/audit` | Audit log — every action with approve/reject/rollback controls |
| `/experiments` | A/B experiment results |
| `/traces` | Distributed trace waterfall viewer |

**API reference:** http://localhost:8000/docs (Swagger UI auto-generated)

---

## All API endpoints

```
GET  /health                              Server health + active model
GET  /campaigns/                          List all campaigns
GET  /campaigns/{id}/metrics              Live metrics for one campaign
GET  /campaigns/{id}/history              24h snapshot history

POST /agent/workflow/run                  Start multi-agent workflow (SSE stream)
POST /agent/sessions/{id}/resume          Resume after human approval
GET  /agent/sessions/{id}/state           Current LangGraph state snapshot

GET  /audit/                              Audit log
POST /audit/{id}/approve                  Approve a pending action
POST /audit/{id}/reject                   Reject a pending action
POST /audit/{id}/rollback                 Roll back a completed action

GET  /telemetry/aggregate                 Aggregate metric (CPA, ROAS, pacing…)
GET  /telemetry/compare                   Cross-campaign leaderboard
GET  /telemetry/timeseries/{id}           Hourly time-series for one campaign

GET  /evals/cases                         List golden eval cases
POST /evals/run                           Run eval suite
POST /evals/run/{case_id}                 Run single eval case
POST /evals/experiment/ab                 Run A/B experiment (agent vs baseline)
GET  /evals/results/latest                Most recent suite result

GET  /experiments/                        A/B experiments
GET  /traces/                             Trace index
GET  /traces/{trace_id}                   Trace detail
```

---

## Configuration reference

All settings are read from `backend/.env` (environment variables override `.env` values).

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required.** Claude API key |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Model used by all agent nodes |
| `DATABASE_URL` | `sqlite+aiosqlite:///./autobid.db` | SQLAlchemy async URL |
| `CHROMA_PATH` | `./chroma_db` | ChromaDB persistence directory |
| `REDIS_URL` | `redis://localhost:6379/0` | Pre-action snapshot store. Leave blank to use in-process fallback. |
| `LANGSMITH_API_KEY` | — | Optional. Enables LangSmith tracing. |
| `LANGCHAIN_PROJECT` | `AutoBid` | LangSmith project name |
| `LLM_TIMEOUT_SECONDS` | `30` | Per-node LLM call timeout |
| `CIRCUIT_BREAKER_FAILURE_THRESHOLD` | `3` | Failures before circuit opens |
| `CIRCUIT_BREAKER_RECOVERY_SECONDS` | `60` | Seconds before circuit probes again |
| `DRY_RUN_DEFAULT` | `false` | Default dry-run state for new sessions |
| `MAX_AGENT_ITERATIONS` | `10` | Maximum workflow iteration loops |

---

## Troubleshooting

**Backend fails to start**
- Check Python version: `python3 --version` — must be 3.11+
- Re-run `uv pip install -e .` from the `backend/` directory
- Confirm `ANTHROPIC_API_KEY` is set in `backend/.env`

**"No campaigns" on the dashboard**
- The backend may still be starting. Wait for `Application startup complete.` in the terminal.
- Check CORS: frontend must run on port 3000 (default); change `cors_origins` in `config.py` if using a different port.

**Agent returns no actions**
- Try a more specific goal: "Fix under-pacing on Whole Foods campaign"
- Check the optimizer's stream events in the console for parse errors
- Confirm the Claude model is reachable: `curl http://localhost:8000/health`

**Eval suite is slow**
- Each case makes two LLM calls (optimizer + judge). The full 15-case suite takes 2–4 minutes depending on API latency.
- Run a single category to test quickly: `{"category": "anomaly"}` (6 cases)

**LangSmith traces not appearing**
- Confirm `LANGSMITH_API_KEY` is in `backend/.env` and the server was restarted after adding it
- Check the project name: traces appear under the `AutoBid` project at smith.langchain.com

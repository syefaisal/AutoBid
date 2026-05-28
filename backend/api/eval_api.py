"""
Eval API — trigger evaluation runs and A/B experiments via REST.

Endpoints:
  GET  /evals/cases                   list all golden cases
  POST /evals/run                     run full suite (or filtered subset)
  POST /evals/run/{case_id}           run single case
  POST /evals/experiment/ab           run A/B comparison (agent vs baseline)
  GET  /evals/results/latest          return latest suite result
"""
from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from evals.dataset import GOLDEN_CASES, CASES_BY_ID
from evals.harness import EvalHarness, EvalResult, EvalSuiteResult
from evals.langsmith_runner import run_ab_experiment, ExperimentResult

router = APIRouter(prefix="/evals", tags=["evals"])

# In-memory cache of the most recent suite result
_latest_suite: EvalSuiteResult | None = None
_latest_experiment: ExperimentResult | None = None


# ── Request / response models ─────────────────────────────────────────────────

class RunSuiteRequest(BaseModel):
    case_ids: list[str] | None = None
    category: str | None = None     # "anomaly" | "policy_rule" | "tool_selection"


class ABExperimentRequest(BaseModel):
    category: str = "anomaly"
    experiment_name: str | None = None


class CaseSummary(BaseModel):
    case_id: str
    category: str
    description: str
    user_goal: str
    expected_action_types: list[str]
    should_trigger_approval: bool
    should_be_blocked_by_audit: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/cases", response_model=list[CaseSummary])
async def list_cases(
    category: Annotated[str | None, Query()] = None,
) -> list[CaseSummary]:
    """Return metadata for all golden cases (no sensitive metric data)."""
    cases = GOLDEN_CASES
    if category:
        cases = [c for c in cases if c.category == category]
    return [
        CaseSummary(
            case_id=c.case_id,
            category=c.category,
            description=c.description,
            user_goal=c.user_goal,
            expected_action_types=c.expected_action_types,
            should_trigger_approval=c.should_trigger_approval,
            should_be_blocked_by_audit=c.should_be_blocked_by_audit,
        )
        for c in cases
    ]


@router.post("/run", response_model=EvalSuiteResult)
async def run_suite(request: RunSuiteRequest) -> EvalSuiteResult:
    """
    Run the evaluation harness against the golden dataset.

    Pass `case_ids` to run specific cases, `category` to run all cases in a
    category, or omit both to run the full suite.
    """
    global _latest_suite
    harness = EvalHarness()
    result = await harness.run_suite(
        case_ids=request.case_ids,
        category=request.category,
    )
    _latest_suite = result
    return result


@router.post("/run/{case_id}", response_model=EvalResult)
async def run_single_case(case_id: str) -> EvalResult:
    """Run a single golden case and return its detailed result."""
    case = CASES_BY_ID.get(case_id)
    if not case:
        raise HTTPException(
            status_code=404,
            detail=f"Case '{case_id}' not found. "
                   f"Available: {sorted(CASES_BY_ID.keys())}",
        )
    harness = EvalHarness()
    return await harness.run_case(case)


@router.post("/experiment/ab", response_model=ExperimentResult)
async def run_ab(request: ABExperimentRequest) -> ExperimentResult:
    """
    Run A/B experiment comparing the autonomous agent (Group B) against the
    rule-based baseline (Group A) on golden cases.

    Results are logged to Braintrust if BRAINTRUST_API_KEY is configured.
    """
    global _latest_experiment
    result = await run_ab_experiment(
        category=request.category,
        experiment_name=request.experiment_name,
    )
    _latest_experiment = result
    return result


@router.get("/results/latest", response_model=EvalSuiteResult | None)
async def get_latest_results() -> EvalSuiteResult | None:
    """Return the most recent suite run result (in-memory, reset on server restart)."""
    return _latest_suite


@router.get("/experiment/latest", response_model=ExperimentResult | None)
async def get_latest_experiment() -> ExperimentResult | None:
    """Return the most recent A/B experiment result."""
    return _latest_experiment

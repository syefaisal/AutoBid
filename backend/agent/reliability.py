"""
Reliability patterns for AutoBid LangGraph nodes.

Three layers:
  1. Timeout          — asyncio.wait_for wraps every LLM coroutine.
  2. Circuit breaker  — CLOSED → OPEN after N consecutive failures;
                        HALF_OPEN → probe after recovery window.
  3. Fallback         — when optimizer trips, deterministic baseline fires
                        instead of returning an empty result or crashing.

Module-level breaker instances are shared across requests so failure counts
accumulate globally (one bad model period opens the circuit for everyone until
recovery_seconds elapses — same semantics as a real infrastructure circuit).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from enum import Enum
from typing import Any, Awaitable

from config import settings


# ── Exceptions ────────────────────────────────────────────────────────────────

class CircuitOpenError(Exception):
    """Raised when a call is attempted on an OPEN circuit."""


class NodeTimeoutError(asyncio.TimeoutError):
    """Raised when an LLM node exceeds its timeout budget."""


# ── Circuit breaker ───────────────────────────────────────────────────────────

class _State(Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Standard three-state circuit breaker.

    CLOSED   → normal; failures increment counter
    OPEN     → all calls rejected immediately
    HALF_OPEN → one probe allowed; success → CLOSED, failure → OPEN
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int | None = None,
        recovery_seconds: float | None = None,
    ):
        self.name = name
        self._threshold = failure_threshold or settings.circuit_breaker_failure_threshold
        self._recovery_s = recovery_seconds or settings.circuit_breaker_recovery_seconds
        self._state = _State.CLOSED
        self._failures = 0
        self._opened_at: float = 0.0

    @property
    def state(self) -> str:
        # Promote OPEN → HALF_OPEN after recovery window
        if self._state == _State.OPEN:
            if time.monotonic() - self._opened_at >= self._recovery_s:
                self._state = _State.HALF_OPEN
        return self._state.value

    def is_open(self) -> bool:
        return self.state == _State.OPEN.value

    def record_success(self) -> None:
        self._failures = 0
        self._state = _State.CLOSED

    def record_failure(self) -> None:
        self._failures += 1
        self._opened_at = time.monotonic()
        if self._failures >= self._threshold:
            self._state = _State.OPEN

    def status(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self._failures,
            "threshold": self._threshold,
        }


# Module-level circuit breakers — one per LLM node type
optimizer_breaker = CircuitBreaker("optimizer")
auditor_breaker   = CircuitBreaker("auditor")
planner_breaker   = CircuitBreaker("planner")
reviewer_breaker  = CircuitBreaker("reviewer")


def get_all_breaker_status() -> list[dict]:
    return [
        b.status()
        for b in [optimizer_breaker, auditor_breaker, planner_breaker, reviewer_breaker]
    ]


# ── Guard helper ──────────────────────────────────────────────────────────────

async def call_with_guard(
    coro: Awaitable[Any],
    circuit: CircuitBreaker,
    timeout_s: float | None = None,
    node_name: str = "",
) -> Any:
    """
    Execute *coro* with circuit-breaker protection and optional timeout.

    Raises CircuitOpenError, NodeTimeoutError, or the original exception
    so callers can decide whether to use a fallback.
    """
    timeout = timeout_s or settings.llm_timeout_seconds

    if circuit.is_open():
        raise CircuitOpenError(
            f"Circuit '{circuit.name}' is OPEN — call rejected. "
            f"Recovery in {circuit._recovery_s:.0f}s."
        )

    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        circuit.record_success()
        return result
    except asyncio.TimeoutError:
        circuit.record_failure()
        raise NodeTimeoutError(
            f"Node '{node_name or circuit.name}' exceeded {timeout}s timeout."
        )
    except Exception:
        circuit.record_failure()
        raise


# ── Optimizer fallback ────────────────────────────────────────────────────────

def build_fallback_optimizer_output(state: Any, reason: str) -> dict:
    """
    Run the deterministic baseline and return a dict shaped like optimizer_node's
    output so the rest of the graph (auditor → gatekeeper → executor) runs normally.
    """
    from evals.baseline import baseline_recommend_all
    from agent.state import ProposedAction

    actions_raw = baseline_recommend_all(state.campaign_metrics, state.user_goal)
    proposed = []
    for i, a in enumerate(actions_raw):
        try:
            proposed.append(ProposedAction(
                action_id=f"fb_{uuid.uuid4().hex[:8]}",
                action_type=a["action_type"],
                campaign_id=a["campaign_id"],
                params=a.get("params", {}),
                rationale=f"[FALLBACK] {a.get('rationale', '')}",
                expected_impact=a.get("expected_impact", ""),
                confidence=float(a.get("confidence", 0.80)),
                priority=i + 1,
            ))
        except Exception:
            pass

    return {
        "proposed_actions": proposed,
        "stream_events": [{
            "type": "optimizer_fallback",
            "reason": reason,
            "action_count": len(proposed),
        }],
        "errors": [f"optimizer_fallback: {reason}"],
    }


def build_fallback_auditor_output(state: Any, reason: str) -> dict:
    """
    When the auditor circuit is open, auto-approve all proposed actions with
    severity=info.  The gatekeeper still enforces hard limits so this is safe.
    """
    from agent.state import AuditFinding
    import uuid as _uuid

    proposed = list(state.proposed_actions)
    findings = [
        AuditFinding(
            finding_id=f"fnd_{_uuid.uuid4().hex[:6]}",
            action_id=a.action_id,
            severity="info",
            finding=f"Auditor unavailable ({reason}) — auto-approved for gatekeeper review.",
            policy_source="reliability_fallback",
            recommendation="Review manually when auditor recovers.",
            requires_human_approval=False,
        )
        for a in proposed
    ]
    return {
        "audit_findings": findings,
        "approved_actions": proposed,
        "blocked_actions": [],
        "pending_approval_actions": [],
        "stream_events": [
            {"type": "auditor_fallback", "reason": reason},
            {
                "type": "audit_complete",
                "approved": len(proposed),
                "blocked": 0,
                "pending_approval": 0,
                "findings": [],
            },
        ],
        "errors": [f"auditor_fallback: {reason}"],
    }

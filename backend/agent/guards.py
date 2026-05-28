"""
Tool execution guardrails — applied via the @tool_guard decorator on every
campaign control function in agent/tools.py.

Enforces in order:
  1. Rate limiting     — sliding-window counter per session_id
  2. Idempotency check — return the existing audit result if the exact same
                         (campaign_id, action_type, params) was already executed
  3. Hard per-step Δ   — block changes that exceed absolute single-step limits
                         even if they would otherwise pass the approval gate
"""
from __future__ import annotations

import time
import logging
from collections import defaultdict
from functools import wraps
from typing import Callable, Optional

from config import settings

logger = logging.getLogger(__name__)


# ── Sliding-window rate limiter ───────────────────────────────────────────────

class _SlidingWindowRateLimiter:
    """
    In-process sliding window rate limiter.
    Keyed by session_id; limit is `max_per_minute` calls per 60-second window.
    """

    def __init__(self, max_per_minute: int) -> None:
        self._max = max_per_minute
        self._windows: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window = self._windows[key]
        # Evict timestamps older than 60 s
        cutoff = now - 60.0
        self._windows[key] = [t for t in window if t >= cutoff]
        if len(self._windows[key]) >= self._max:
            return False
        self._windows[key].append(now)
        return True

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        cutoff = now - 60.0
        active = [t for t in self._windows[key] if t >= cutoff]
        return max(0, self._max - len(active))


_rate_limiter = _SlidingWindowRateLimiter(settings.rate_limit_actions_per_minute)


# ── Per-step hard limits ──────────────────────────────────────────────────────
# These are ABSOLUTE blocks — even a human-approved request is rejected if it
# would change a value by more than this fraction in a single execution step.
# The approval gate (25% budget, 50% bid) still applies; these are additional
# ceilings that cannot be overridden.

STEP_HARD_LIMITS: dict[str, float] = {
    "update_bid_modifier": settings.max_bid_modifier_step_pct,   # default 0.20 = 20%
    "update_budget":       settings.max_budget_step_pct,          # default 0.50 = 50%
}


def _check_step_limit(action_type: str, before: dict, requested: dict) -> Optional[str]:
    """
    Return an error string if the requested change exceeds the hard per-step
    limit, or None if the change is within bounds.
    """
    limit = STEP_HARD_LIMITS.get(action_type)
    if limit is None:
        return None

    if action_type == "update_bid_modifier":
        old = before.get("bid_modifier", 1.0)
        new = requested.get("bid_modifier", old)
        if old != 0 and abs(new - old) / abs(old) > limit:
            return (
                f"bid_modifier change of {abs(new-old)/old:.0%} exceeds "
                f"hard per-step limit of {limit:.0%} "
                f"(from {old:.3f} to {new:.3f})"
            )

    elif action_type == "update_budget":
        old = before.get("daily_budget_usd", 1)
        new = requested.get("daily_budget_usd", old)
        if old != 0 and abs(new - old) / abs(old) > limit:
            return (
                f"daily_budget change of {abs(new-old)/old:.0%} exceeds "
                f"hard per-step limit of {limit:.0%} "
                f"(from ${old:.0f} to ${new:.0f})"
            )

    return None


# ── @tool_guard decorator ─────────────────────────────────────────────────────

def tool_guard(action_type: str) -> Callable:
    """
    Decorator for campaign control tool functions.

    Wraps every tool with three pre-execution checks:
      1. Rate limit  — abort with status="rate_limited" if over quota
      2. Idempotency — return existing audit result if already executed
      3. Hard limits — block catastrophic single-step changes

    Usage::

        @tool_guard("update_bid_modifier")
        async def update_bid_modifier(db, campaign_id, ...) -> dict:
            ...

    The decorated function must accept ``session_id``, ``is_dry_run``,
    and a ``db`` SQLAlchemy AsyncSession as keyword-or-positional args.
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args, **kwargs) -> dict:
            session_id = kwargs.get("session_id", "default")
            is_dry_run = kwargs.get("is_dry_run", False)
            db         = kwargs.get("db") or (args[0] if args else None)

            # ── 1. Rate limit ─────────────────────────────────────────────────
            if not is_dry_run and not _rate_limiter.allow(session_id):
                remaining_s = 60
                logger.warning(
                    "Rate limit exceeded for session %s on %s", session_id, action_type
                )
                return {
                    "error": (
                        f"Rate limit exceeded ({settings.rate_limit_actions_per_minute} "
                        f"actions/min). Retry in ~{remaining_s}s."
                    ),
                    "status": "rate_limited",
                    "audit_id": "",
                }

            # ── 2. Idempotency check ──────────────────────────────────────────
            # Build the idempotency key the same way tools.py does, then check
            # whether we already have a completed/dry_run result for it.
            if db is not None and not is_dry_run:
                import hashlib, json as _json
                from sqlalchemy import select as _select
                from models.audit import AuditLog, ActionStatus

                # Reconstruct params_requested from kwargs
                _param_map = {
                    "update_bid_modifier":  lambda kw: {"bid_modifier": kw.get("new_bid_modifier")},
                    "update_budget":        lambda kw: {"daily_budget_usd": kw.get("new_daily_budget_usd")},
                    "pause_campaign":       lambda kw: {},
                    "update_targeting":     lambda kw: kw.get("targeting_updates", {}),
                    "update_supply_sources": lambda kw: {
                        "add_sources": kw.get("add_sources", []),
                        "remove_sources": kw.get("remove_sources", []),
                    },
                    "route_creative":       lambda kw: {"creative_weights": kw.get("creative_weights", {})},
                }
                params_requested = _param_map.get(action_type, lambda _: {})(kwargs)
                campaign_id = kwargs.get("campaign_id", "")
                ikey_payload = f"{campaign_id}:{action_type}:{_json.dumps(params_requested, sort_keys=True)}"
                ikey = hashlib.sha256(ikey_payload.encode()).hexdigest()[:32]

                try:
                    existing = await db.execute(
                        _select(AuditLog)
                        .where(AuditLog.idempotency_key == ikey)
                        .where(AuditLog.status.in_([
                            ActionStatus.completed,
                            ActionStatus.dry_run,
                        ]))
                        .limit(1)
                    )
                    log = existing.scalar_one_or_none()
                    if log:
                        logger.info(
                            "Idempotent: returning existing result for %s (audit_id=%s)",
                            action_type, log.id,
                        )
                        return {
                            "action":     action_type,
                            "audit_id":   log.id,
                            "campaign_id": campaign_id,
                            "status":     log.status,
                            "idempotent": True,
                            "message":    "Returned existing result (idempotency key matched).",
                        }
                except Exception as exc:
                    logger.warning("Idempotency DB check failed: %s", exc)

            # ── 3. Hard per-step change limit ─────────────────────────────────
            # Fetch current campaign state to compute the Δ before executing.
            if db is not None and action_type in STEP_HARD_LIMITS:
                from agent.tools import _get_campaign as _gc
                campaign_id = kwargs.get("campaign_id", "")
                try:
                    campaign = await _gc(db, campaign_id)
                    if campaign:
                        before = {
                            "bid_modifier":     campaign.bid_modifier,
                            "daily_budget_usd": campaign.daily_budget_usd,
                        }
                        requested = {
                            "bid_modifier":     kwargs.get("new_bid_modifier", campaign.bid_modifier),
                            "daily_budget_usd": kwargs.get("new_daily_budget_usd", campaign.daily_budget_usd),
                        }
                        err = _check_step_limit(action_type, before, requested)
                        if err:
                            logger.warning("Hard limit blocked %s on %s: %s", action_type, campaign_id, err)
                            return {
                                "error":       f"Hard step-limit violation: {err}",
                                "status":      "blocked",
                                "audit_id":    "",
                                "campaign_id": campaign_id,
                                "action_type": action_type,
                            }
                except Exception as exc:
                    logger.warning("Hard-limit pre-check failed: %s", exc)

            return await fn(*args, **kwargs)

        return wrapper
    return decorator

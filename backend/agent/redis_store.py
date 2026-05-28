"""
Pre-action campaign state snapshots for automatic rollback.

Uses Redis when available (configured via REDIS_URL).  Falls back to an
in-process dict when Redis is unreachable — sufficient for single-instance
demo; swap for a real Redis cluster in production.

Snapshot lifecycle
──────────────────
1. Before execution  : write_snapshot(audit_id, campaign_state)
2. After execution   : validate_post_state(campaign_state)
3. On failure        : read_snapshot(audit_id) → apply to DB → delete_snapshot
4. On success        : delete_snapshot (or let TTL expire)
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import redis.asyncio as aioredis

from config import settings

logger = logging.getLogger(__name__)

# In-process fallback store (used when Redis is unreachable)
_fallback: dict[str, str] = {}


async def _get_redis() -> Optional[aioredis.Redis]:
    if not settings.redis_url:
        return None
    try:
        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        return client
    except Exception as exc:
        logger.warning("Redis unavailable (%s); using in-process fallback.", exc)
        return None


async def write_snapshot(audit_id: str, campaign_state: dict) -> None:
    """
    Persist the pre-action campaign state snapshot keyed by audit_id.
    Written before any mutation so rollback can restore exact prior state.
    """
    payload = json.dumps(campaign_state)
    redis = await _get_redis()
    if redis:
        try:
            await redis.setex(
                f"snapshot:{audit_id}",
                settings.snapshot_ttl_seconds,
                payload,
            )
            return
        except Exception as exc:
            logger.warning("Redis write failed (%s); falling back.", exc)
    _fallback[f"snapshot:{audit_id}"] = payload


async def read_snapshot(audit_id: str) -> Optional[dict]:
    """Return the stored pre-action state, or None if it has expired / not found."""
    redis = await _get_redis()
    if redis:
        try:
            raw = await redis.get(f"snapshot:{audit_id}")
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.warning("Redis read failed (%s); trying fallback.", exc)
    raw = _fallback.get(f"snapshot:{audit_id}")
    return json.loads(raw) if raw else None


async def delete_snapshot(audit_id: str) -> None:
    """Remove snapshot after successful execution or explicit discard."""
    redis = await _get_redis()
    if redis:
        try:
            await redis.delete(f"snapshot:{audit_id}")
        except Exception:
            pass
    _fallback.pop(f"snapshot:{audit_id}", None)


# ── Post-execution state validator ────────────────────────────────────────────

class PostExecutionValidationError(Exception):
    """Raised when a campaign ends up in an unsafe state after execution."""


CAMPAIGN_STATE_RULES: dict[str, tuple] = {
    # field_name: (min, max) — None means unconstrained
    "bid_modifier":      (0.50, 2.00),
    "daily_budget_usd":  (1.0,  None),
}


def validate_campaign_state(state: dict) -> None:
    """
    Assert that a post-execution campaign state is within safe bounds.
    Raises PostExecutionValidationError with a descriptive message if not.
    Called by tools.py after every write; triggers auto-rollback on failure.
    """
    errors: list[str] = []
    for field, (lo, hi) in CAMPAIGN_STATE_RULES.items():
        val = state.get(field)
        if val is None:
            continue
        if lo is not None and val < lo:
            errors.append(f"{field}={val} is below minimum {lo}")
        if hi is not None and val > hi:
            errors.append(f"{field}={val} exceeds maximum {hi}")

    if state.get("status") == "active" and state.get("daily_budget_usd", 1) <= 0:
        errors.append("active campaign has zero or negative daily_budget_usd")

    if errors:
        raise PostExecutionValidationError("; ".join(errors))

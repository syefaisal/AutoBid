from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, JSON, Text
from sqlalchemy.sql import func
from models.db import Base
import enum


class ActionStatus(str, enum.Enum):
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    executing = "executing"
    completed = "completed"
    failed = "failed"
    rolled_back = "rolled_back"
    dry_run = "dry_run"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True)
    idempotency_key = Column(String, unique=True, nullable=False, index=True)
    trace_id = Column(String, nullable=False, index=True)
    span_id = Column(String, nullable=False)

    # Action metadata
    action_type = Column(String, nullable=False)  # update_bid, update_budget, pause, etc.
    campaign_id = Column(String, nullable=False, index=True)
    agent_session_id = Column(String, nullable=False)

    # State transitions
    status = Column(String, default=ActionStatus.pending_approval)
    is_dry_run = Column(Boolean, default=False)
    requires_approval = Column(Boolean, default=False)
    approved_by = Column(String, nullable=True)

    # Payload
    params_before = Column(JSON, default=dict)  # snapshot before
    params_requested = Column(JSON, default=dict)  # what agent requested
    params_after = Column(JSON, nullable=True)  # actual result

    # Reasoning
    agent_rationale = Column(Text, nullable=True)
    rag_sources = Column(JSON, default=list)  # which docs grounded this decision

    # Rollback
    rollback_params = Column(JSON, nullable=True)
    rolled_back_at = Column(DateTime, nullable=True)

    # Timing
    created_at = Column(DateTime, server_default=func.now())
    executed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    latency_ms = Column(Integer, nullable=True)

    # Error handling
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id = Column(String, primary_key=True)
    trace_id = Column(String, nullable=False, index=True)
    campaign_ids = Column(JSON, default=list)
    user_query = Column(Text, nullable=False)
    is_dry_run = Column(Boolean, default=False)
    status = Column(String, default="running")  # running, completed, failed

    # Metrics
    total_tokens_input = Column(Integer, default=0)
    total_tokens_output = Column(Integer, default=0)
    tool_calls_count = Column(Integer, default=0)
    rag_retrievals_count = Column(Integer, default=0)
    actions_taken = Column(Integer, default=0)
    actions_pending_approval = Column(Integer, default=0)

    # Full conversation
    messages = Column(JSON, default=list)
    final_answer = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)
    total_latency_ms = Column(Integer, nullable=True)


class Experiment(Base):
    __tablename__ = "experiments"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    hypothesis = Column(Text)
    metric = Column(String, nullable=False)  # cpa, roas, ctr, etc.
    status = Column(String, default="running")  # running, completed, paused

    control_campaign_ids = Column(JSON, default=list)
    treatment_campaign_ids = Column(JSON, default=list)

    control_metric_value = Column(Float, nullable=True)
    treatment_metric_value = Column(Float, nullable=True)
    lift_pct = Column(Float, nullable=True)
    p_value = Column(Float, nullable=True)
    is_significant = Column(Boolean, nullable=True)

    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

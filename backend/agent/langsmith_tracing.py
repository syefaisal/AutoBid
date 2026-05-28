"""
LangSmith end-to-end tracing setup for AutoBid.

Call setup_langsmith_tracing() once at application startup.  After that:

  LangGraph nodes        → traced automatically (LangGraph ↔ LangSmith native)
  ChatAnthropic LLM calls → traced automatically (LangChain ↔ LangSmith native)
  Tool arguments          → captured as child runs under each node run
  RAG retrieve()          → traced via @traceable in rag/retriever.py (explicit)

The trace hierarchy in the LangSmith UI looks like:

  workflow_run  (LangGraph graph run)
    └─ planner_node
    └─ analyst_node
         └─ rag_retrieve  ← @traceable: query + retrieved docs + latency
    └─ optimizer_node
         └─ ChatAnthropic ← auto-traced: messages, tool calls, token counts
    └─ auditor_node
         └─ ChatAnthropic
    └─ gatekeeper_node
    └─ executor_node
    └─ reviewer_node
         └─ ChatAnthropic

All traces land in the project specified by LANGCHAIN_PROJECT (default: AutoBid).
"""
from __future__ import annotations

import os
import logging

log = logging.getLogger(__name__)


def setup_langsmith_tracing() -> bool:
    """
    Configure LangSmith tracing by setting the standard LangChain env vars.

    Called once from main.py lifespan.  Returns True if tracing is active.
    LangChain reads these vars lazily so they must be set before the first
    graph run, not before import.
    """
    from config import settings

    api_key = getattr(settings, "langsmith_api_key", "")
    if not api_key:
        log.info("LangSmith tracing disabled — LANGSMITH_API_KEY not set")
        return False

    project = getattr(settings, "langchain_project", "AutoBid")

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"]    = api_key
    os.environ["LANGCHAIN_PROJECT"]    = project

    log.info("LangSmith tracing enabled → project=%s", project)
    return True


def is_tracing_active() -> bool:
    return os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"

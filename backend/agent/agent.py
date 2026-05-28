"""
AutoBid Agent Orchestrator
Implements the agentic loop: retrieve → reason → act → verify
with full observability, safety gates, and RAG grounding.
"""
import uuid
import time
import json
import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

from config import settings
from models.audit import AgentSession
from agent.prompts import SYSTEM_PROMPT, TOOL_DEFINITIONS
import agent.tools as tools
from rag.retriever import retrieve, format_context_for_prompt
from telemetry.tracing import agent_tracer, rag_tracer, tool_tracer

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


class AgentOrchestrator:
    def __init__(self, db: AsyncSession, is_dry_run: bool = False):
        self.db = db
        self.is_dry_run = is_dry_run
        self.session_id = str(uuid.uuid4())
        self.trace_id = str(uuid.uuid4()).replace("-", "")
        self.messages: list[dict] = []
        self.rag_sources_used: list[dict] = []
        self.tool_calls_count = 0
        self.rag_retrievals_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    async def _execute_tool(self, tool_name: str, tool_input: dict, span_id: str) -> dict:
        """Dispatch tool call to implementation with tracing."""
        async with tool_tracer.span(f"tool:{tool_name}", trace_id=self.trace_id, parent_span_id=span_id) as span:
            span.set_attribute("tool.name", tool_name)
            span.set_attribute("tool.input", json.dumps(tool_input)[:500])
            span.set_attribute("dry_run", self.is_dry_run)

            common = dict(
                db=self.db,
                session_id=self.session_id,
                trace_id=self.trace_id,
                span_id=span.span_id,
                rag_sources=[r["source"] for r in self.rag_sources_used[-5:]],
                is_dry_run=self.is_dry_run,
            )

            if tool_name == "get_campaign_metrics":
                result = await tools.get_campaign_metrics(
                    self.db, tool_input["campaign_id"],
                    self.session_id, self.trace_id
                )
            elif tool_name == "retrieve_policy":
                async with rag_tracer.span("rag:retrieve", trace_id=self.trace_id, parent_span_id=span_id) as rag_span:
                    rag_span.set_attribute("query", tool_input["query"])
                    results = retrieve(
                        query=tool_input["query"],
                        campaign_id=tool_input.get("campaign_id"),
                        n_results=5,
                    )
                    self.rag_retrievals_count += 1
                    self.rag_sources_used.extend(results)
                    rag_span.set_attribute("results_count", len(results))
                    context = format_context_for_prompt(results)
                    result = {
                        "retrieved_context": context,
                        "sources": [r["source"] for r in results],
                        "result_count": len(results),
                    }
            elif tool_name == "update_bid_modifier":
                result = await tools.update_bid_modifier(
                    rationale=tool_input["rationale"],
                    new_bid_modifier=tool_input["new_bid_modifier"],
                    campaign_id=tool_input["campaign_id"],
                    **common,
                )
            elif tool_name == "update_budget":
                result = await tools.update_budget(
                    rationale=tool_input["rationale"],
                    new_daily_budget_usd=tool_input["new_daily_budget_usd"],
                    campaign_id=tool_input["campaign_id"],
                    **common,
                )
            elif tool_name == "pause_campaign":
                result = await tools.pause_campaign(
                    rationale=tool_input["rationale"],
                    campaign_id=tool_input["campaign_id"],
                    **common,
                )
            elif tool_name == "update_targeting":
                result = await tools.update_targeting(
                    rationale=tool_input["rationale"],
                    targeting_updates=tool_input["targeting_updates"],
                    campaign_id=tool_input["campaign_id"],
                    **common,
                )
            elif tool_name == "update_supply_sources":
                result = await tools.update_supply_sources(
                    rationale=tool_input["rationale"],
                    add_sources=tool_input.get("add_sources", []),
                    remove_sources=tool_input.get("remove_sources", []),
                    campaign_id=tool_input["campaign_id"],
                    **common,
                )
            elif tool_name == "route_creative":
                result = await tools.route_creative(
                    rationale=tool_input["rationale"],
                    creative_weights=tool_input["creative_weights"],
                    campaign_id=tool_input["campaign_id"],
                    **common,
                )
            else:
                result = {"error": f"Unknown tool: {tool_name}"}

            span.set_attribute("tool.result_status", result.get("status", result.get("error", "ok")))
            return result

    async def run(self, user_query: str) -> AsyncGenerator[dict, None]:
        """
        Run the agent loop, yielding streaming events for real-time UI updates.
        Event types: thinking, tool_call, tool_result, text_delta, done, error
        """
        t0 = time.time()

        # Create session record
        session = AgentSession(
            id=self.session_id,
            trace_id=self.trace_id,
            user_query=user_query,
            is_dry_run=self.is_dry_run,
            status="running",
        )
        self.db.add(session)
        await self.db.commit()

        async with agent_tracer.span("agent:run", trace_id=self.trace_id) as root_span:
            root_span.set_attribute("query", user_query[:200])
            root_span.set_attribute("dry_run", self.is_dry_run)

            self.messages = [{"role": "user", "content": user_query}]

            dry_run_prefix = "\n\n[DRY RUN MODE — no changes will be persisted]" if self.is_dry_run else ""

            iteration = 0
            final_text = ""

            try:
                while iteration < settings.max_agent_iterations:
                    iteration += 1

                    async with agent_tracer.span(
                        f"agent:iteration:{iteration}",
                        trace_id=self.trace_id,
                        parent_span_id=root_span.span_id,
                    ) as iter_span:
                        iter_span.set_attribute("iteration", iteration)

                        # Stream Claude response
                        assistant_content = []
                        current_tool_calls = []
                        text_buffer = ""

                        async with client.messages.stream(
                            model=settings.claude_model,
                            max_tokens=4096,
                            system=SYSTEM_PROMPT + dry_run_prefix,
                            tools=TOOL_DEFINITIONS,
                            messages=self.messages,
                        ) as stream:
                            async for event in stream:
                                if hasattr(event, "type"):
                                    if event.type == "content_block_start":
                                        block = event.content_block
                                        if block.type == "text":
                                            pass  # start text block
                                        elif block.type == "tool_use":
                                            current_tool_calls.append({
                                                "id": block.id,
                                                "name": block.name,
                                                "input": {},
                                                "_input_str": "",
                                            })

                                    elif event.type == "content_block_delta":
                                        delta = event.delta
                                        if delta.type == "text_delta":
                                            text_buffer += delta.text
                                            yield {"type": "text_delta", "text": delta.text, "session_id": self.session_id}
                                        elif delta.type == "input_json_delta":
                                            if current_tool_calls:
                                                current_tool_calls[-1]["_input_str"] += delta.partial_json

                                    elif event.type == "content_block_stop":
                                        if current_tool_calls and current_tool_calls[-1].get("_input_str"):
                                            tc = current_tool_calls[-1]
                                            try:
                                                tc["input"] = json.loads(tc["_input_str"])
                                            except json.JSONDecodeError:
                                                tc["input"] = {}

                                    elif event.type == "message_delta":
                                        if hasattr(event, "usage"):
                                            self.total_output_tokens += event.usage.output_tokens or 0

                                    elif event.type == "message_start":
                                        if hasattr(event, "message") and hasattr(event.message, "usage"):
                                            self.total_input_tokens += event.message.usage.input_tokens or 0

                            # Get final message
                            final_msg = await stream.get_final_message()

                        stop_reason = final_msg.stop_reason

                        # Build assistant content block
                        for block in final_msg.content:
                            if block.type == "text":
                                if text_buffer:
                                    assistant_content.append({"type": "text", "text": text_buffer})
                                    final_text = text_buffer
                                    text_buffer = ""
                            elif block.type == "tool_use":
                                assistant_content.append({
                                    "type": "tool_use",
                                    "id": block.id,
                                    "name": block.name,
                                    "input": block.input,
                                })

                        self.messages.append({"role": "assistant", "content": final_msg.content})

                        if stop_reason == "end_turn":
                            break

                        if stop_reason == "tool_use":
                            # Execute all tool calls
                            tool_results = []
                            for block in final_msg.content:
                                if block.type != "tool_use":
                                    continue
                                self.tool_calls_count += 1

                                yield {
                                    "type": "tool_call",
                                    "tool_name": block.name,
                                    "tool_input": block.input,
                                    "tool_use_id": block.id,
                                    "session_id": self.session_id,
                                }

                                result = await self._execute_tool(block.name, block.input, iter_span.span_id)

                                yield {
                                    "type": "tool_result",
                                    "tool_name": block.name,
                                    "tool_use_id": block.id,
                                    "result": result,
                                    "session_id": self.session_id,
                                }

                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": json.dumps(result),
                                })

                            self.messages.append({"role": "user", "content": tool_results})

                # Update session
                total_ms = int((time.time() - t0) * 1000)
                await self.db.execute(
                    update(AgentSession).where(AgentSession.id == self.session_id).values(
                        status="completed",
                        total_tokens_input=self.total_input_tokens,
                        total_tokens_output=self.total_output_tokens,
                        tool_calls_count=self.tool_calls_count,
                        rag_retrievals_count=self.rag_retrievals_count,
                        messages=json.dumps([str(m) for m in self.messages]),
                        final_answer=final_text,
                        completed_at=datetime.now(timezone.utc),
                        total_latency_ms=total_ms,
                    )
                )
                await self.db.commit()

                yield {
                    "type": "done",
                    "session_id": self.session_id,
                    "trace_id": self.trace_id,
                    "total_latency_ms": total_ms,
                    "tool_calls": self.tool_calls_count,
                    "rag_retrievals": self.rag_retrievals_count,
                    "tokens_in": self.total_input_tokens,
                    "tokens_out": self.total_output_tokens,
                    "dry_run": self.is_dry_run,
                }

            except Exception as e:
                root_span.set_status_error(str(e))
                await self.db.execute(
                    update(AgentSession).where(AgentSession.id == self.session_id).values(
                        status="failed",
                        final_answer=f"Error: {str(e)}",
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await self.db.commit()
                yield {"type": "error", "error": str(e), "session_id": self.session_id}

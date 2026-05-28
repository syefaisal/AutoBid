"""
OpenTelemetry-style in-process tracer with spans stored in SQLite for portfolio demo.
In production this would export to Jaeger/Tempo/Datadog via OTLP.
"""
import time
import uuid
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict


@dataclass
class Span:
    span_id: str
    trace_id: str
    parent_span_id: Optional[str]
    name: str
    service: str
    start_time_ms: float
    end_time_ms: Optional[float] = None
    status: str = "ok"  # ok, error
    attributes: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)

    @property
    def duration_ms(self) -> Optional[float]:
        if self.end_time_ms:
            return self.end_time_ms - self.start_time_ms
        return None

    def add_event(self, name: str, attributes: dict = None):
        self.events.append({
            "name": name,
            "time_ms": time.time() * 1000,
            "attributes": attributes or {}
        })

    def set_attribute(self, key: str, value):
        self.attributes[key] = value

    def set_status_error(self, message: str):
        self.status = "error"
        self.attributes["error.message"] = message


# In-memory trace store (production would use OTLP exporter)
_trace_store: dict[str, list[Span]] = defaultdict(list)
_active_spans: dict[str, Span] = {}


class Tracer:
    def __init__(self, service_name: str):
        self.service_name = service_name

    def start_span(self, name: str, trace_id: str = None, parent_span_id: str = None) -> Span:
        span = Span(
            span_id=str(uuid.uuid4())[:8],
            trace_id=trace_id or str(uuid.uuid4()).replace("-", ""),
            parent_span_id=parent_span_id,
            name=name,
            service=self.service_name,
            start_time_ms=time.time() * 1000,
        )
        _trace_store[span.trace_id].append(span)
        _active_spans[span.span_id] = span
        return span

    def end_span(self, span: Span, status: str = "ok"):
        span.end_time_ms = time.time() * 1000
        span.status = status
        _active_spans.pop(span.span_id, None)

    @asynccontextmanager
    async def span(self, name: str, trace_id: str = None, parent_span_id: str = None):
        s = self.start_span(name, trace_id=trace_id, parent_span_id=parent_span_id)
        try:
            yield s
            self.end_span(s, "ok")
        except Exception as e:
            s.set_status_error(str(e))
            self.end_span(s, "error")
            raise


agent_tracer = Tracer("autobid-agent")
rag_tracer = Tracer("autobid-rag")
api_tracer = Tracer("autobid-api")
tool_tracer = Tracer("autobid-tools")


def get_trace(trace_id: str) -> list[Span]:
    return _trace_store.get(trace_id, [])


def get_all_traces(limit: int = 50) -> list[dict]:
    result = []
    for trace_id, spans in _trace_store.items():
        if not spans:
            continue
        root = next((s for s in spans if s.parent_span_id is None), spans[0])
        result.append({
            "trace_id": trace_id,
            "root_span": root.name,
            "service": root.service,
            "start_time_ms": root.start_time_ms,
            "duration_ms": root.duration_ms,
            "span_count": len(spans),
            "status": "error" if any(s.status == "error" for s in spans) else "ok",
        })
    result.sort(key=lambda x: x["start_time_ms"], reverse=True)
    return result[:limit]


def serialize_trace(trace_id: str) -> dict:
    spans = get_trace(trace_id)
    return {
        "trace_id": trace_id,
        "spans": [
            {
                "span_id": s.span_id,
                "parent_span_id": s.parent_span_id,
                "name": s.name,
                "service": s.service,
                "start_time_ms": s.start_time_ms,
                "end_time_ms": s.end_time_ms,
                "duration_ms": s.duration_ms,
                "status": s.status,
                "attributes": s.attributes,
                "events": s.events,
            }
            for s in spans
        ]
    }

"""
AutoBid Backend — AI-Powered Campaign Control Agent
Production-grade RAG + Agentic Workflows for Programmatic Advertising
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from models import init_db
from agent.langsmith_tracing import setup_langsmith_tracing
from data.seed import seed_campaigns
from rag.retriever import index_policy_documents
from models.db import AsyncSessionLocal

from api.campaigns import router as campaigns_router
from api.agent_api import router as agent_router
from api.audit_api import router as audit_router
from api.experiments_api import router as experiments_router
from api.traces_api import router as traces_router
from api.telemetry_api import router as telemetry_router
from api.eval_api import router as eval_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Configure LangSmith tracing (no-op if LANGSMITH_API_KEY not set)
    setup_langsmith_tracing()

    # Initialize DB schema
    await init_db()

    # Seed demo data
    async with AsyncSessionLocal() as db:
        await seed_campaigns(db)

    # Index policy documents into ChromaDB
    count = index_policy_documents()
    print(f"Indexed {count} policy document chunks into RAG")

    yield


app = FastAPI(
    title="AutoBid API",
    description="AI-powered campaign optimization agent with production-grade RAG",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(campaigns_router)
app.include_router(agent_router)
app.include_router(audit_router)
app.include_router(experiments_router)
app.include_router(traces_router)
app.include_router(telemetry_router)
app.include_router(eval_router)


@app.get("/health")
async def health():
    return {"status": "ok", "model": settings.claude_model}


@app.get("/")
async def root():
    return {
        "service": "AutoBid API",
        "version": "1.0.0",
        "docs": "/docs",
    }

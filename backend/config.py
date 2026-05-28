from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    database_url: str = "sqlite+aiosqlite:///./autobid.db"
    chroma_path: str = "./chroma_db"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3001"]
    max_agent_iterations: int = 10
    dry_run_default: bool = False

    # Rate limiting — enforced in @tool_guard decorator
    rate_limit_actions_per_minute: int = 30

    # Approval gates (route to human sign-off)
    approval_required_budget_change_pct: float = 0.25   # >25% → approval
    approval_required_bid_change_pct: float = 0.50       # >50% → approval

    # Hard per-step change limits (block, even with approval)
    max_bid_modifier_step_pct: float = 0.20              # max ±20% per execution step
    max_budget_step_pct: float = 0.50                    # max ±50% per execution step

    # Redis — for pre-action snapshots and auto-rollback
    # Set to empty string to disable Redis and use in-process fallback
    redis_url: str = "redis://localhost:6379/0"
    snapshot_ttl_seconds: int = 86400                    # 24 h TTL on state snapshots

    # LangSmith — optional; if empty, A/B experiment results are local-only
    langsmith_api_key: str = ""
    langchain_project: str = "AutoBid"   # LangSmith project name

    # LLM reliability — timeouts and circuit breaker
    llm_timeout_seconds: float = 30.0
    circuit_breaker_failure_threshold: int = 3
    circuit_breaker_recovery_seconds: float = 60.0


settings = Settings()

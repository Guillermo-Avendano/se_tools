"""FastAPI application entry point."""

import logging
import structlog
import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Add project root to path for sync script
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.config import settings
from app.api.routes import router
from app.api.openai_compat import openai_router
from app.memory.file_loader import load_files_for_memory, load_knowledge_for_memory

# ─── Repository Configuration Sync ─────────────────────────────
def sync_repository_configurations():
    """Sync environment variables with repository configuration files."""
    try:
        from scripts.sync_repo_configs import sync_repository_config
        sync_repository_config()
        logger.info("app.repository_sync_success")
    except Exception as e:
        logger.warning("app.repository_sync_error", error=str(e))
        logger.info("app.continue_with_existing_configs")

# ─── Structured logging ─────────────────────────────────────
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if settings.log_level == "DEBUG"
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.log_level.upper(), logging.INFO)
    ),
)

logger = structlog.get_logger(__name__)

# ─── Rate limiter ────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["30/minute"])


# ─── Lifespan ────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app.startup", ollama=settings.ollama_base_url, model=settings.ollama_model)
    
    # Sync repository configurations first
    sync_repository_configurations()
    
    try:
        total = load_files_for_memory()
        logger.info("app.files_loaded", chunks=total)
    except Exception as e:
        logger.warning("app.files_load_error", error=str(e))
    try:
        knowledge = load_knowledge_for_memory()
        logger.info("app.knowledge_loaded", chunks=knowledge)
    except Exception as e:
        logger.warning("app.files_load_error", error=str(e))
    yield
    logger.info("app.shutdown")


# ─── App ─────────────────────────────────────────────────────
app = FastAPI(
    title="SE-Content-Agent API",
    description="AI agent with ContentEdge document management capabilities.",
    version="2.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(openai_router)

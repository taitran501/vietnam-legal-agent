"""
FastAPI application entry-point.

Start with:
    uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 2
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from backend.api import metrics as metrics_module
from backend.api.auth import APIKeyMiddleware, get_valid_api_keys
from backend.api.middleware import RateLimiter, RateLimitMiddleware
from backend.config import get_settings
from backend.history import init_history_store
from backend.memory.session_store import close_redis, get_redis

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------

def setup_logging():
    """Configure structured logging for production."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("LOG_FORMAT", "text").lower()
    
    if log_format == "json":
        try:
            from pythonjsonlogger import jsonlogger
            
            handler = logging.StreamHandler()
            formatter = jsonlogger.JsonFormatter(
                '%(asctime)s %(name)s %(levelname)s %(message)s',
                datefmt='%Y-%m-%dT%H:%M:%S'
            )
            handler.setFormatter(formatter)
            
            root_logger = logging.getLogger()
            root_logger.handlers = []
            root_logger.addHandler(handler)
            root_logger.setLevel(getattr(logging, log_level, logging.INFO))
            
            logger.info("JSON logging configured successfully")
        except ImportError:
            logging.basicConfig(
                level=getattr(logging, log_level, logging.INFO),
                format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
                datefmt='%Y-%m-%dT%H:%M:%S'
            )
            logger.warning("python-json-logger not installed, using text format")
    else:
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%dT%H:%M:%S'
        )
        logger.info(f"Text logging configured at {log_level} level")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add unique request ID to each request for log correlation."""
    
    async def dispatch(self, request: Request, call_next):
        import uuid
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        
        return response


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: warm up connections; Shutdown: release resources."""
    # Setup logging first
    setup_logging()
    
    settings = get_settings()
    logger.info("Starting EPR Chatbot backend…")

    # 1. Verify Redis is reachable
    try:
        r = await get_redis()
        await r.ping()
        logger.info("Redis connected at %s", settings.redis_url)
    except Exception as exc:  # noqa: BLE001 - Redis is an optional degraded dependency at startup
        logger.warning("Redis not available: %s — session store will degrade gracefully", exc)

    # 2. Initialize the single durable conversation/case/run repository.
    try:
        await init_history_store()
        logger.info("Persistent history store ready at %s", settings.history_db_path)
    except Exception as exc:  # noqa: BLE001 - persistence failure is reported without blocking shutdown
        logger.warning("Persistent history init failed: %s", exc)

    # 2.5 Warm retrieval indexes asynchronously; readiness still guards requests.
    warmup_task = asyncio.create_task(_warmup_retrieval_indexes_task())

    yield

    # Shutdown
    if not warmup_task.done():
        warmup_task.cancel()
        try:
            await warmup_task
        except asyncio.CancelledError:
            pass
    await close_redis()
    try:
        from epr_agent.infra.persistence import close_persistence_stores

        await close_persistence_stores()
    except Exception as exc:  # noqa: BLE001 - shutdown must close remaining resources
        logger.warning("Persistence store close failed: %s", exc)
    logger.info("EPR Chatbot backend stopped")


async def _warmup_retrieval_indexes_task() -> None:
    """Warm retrieval indexes in background without blocking API availability."""
    try:
        from backend.core.ensemble_retrieval import warmup_retrieval_indexes

        await asyncio.to_thread(warmup_retrieval_indexes)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - readiness, not warmup, owns request safety
        logger.warning("Retrieval index warmup failed: %s", exc)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="EPR Chatbot API",
    description="Vietnamese EPR legal Q&A chatbot with RAG + streaming",
    version="1.0.0",
    lifespan=lifespan,
)

_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost,http://localhost:3000,http://localhost:8501").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Accept", "X-API-Key", "X-Service-Token", "Authorization"],
)

# Add request ID middleware (must be before other middleware for correlation)
app.add_middleware(RequestIDMiddleware)

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# Add rate limiting middleware
app.add_middleware(
    RateLimitMiddleware,
    limiter=RateLimiter(
        rpm=60,    # 60 requests per minute
        rph=1000,  # 1000 requests per hour
        burst=10,  # Allow burst of 10 extra requests
    ),
)

# Add authentication middleware
app.add_middleware(
    APIKeyMiddleware,
    valid_keys=get_valid_api_keys(),
)

# Add metrics middleware
app.add_middleware(metrics_module.MetricsMiddleware)

# Register routers
from backend.api.routes.chat import router as chat_router
from backend.api.routes.feedback import router as feedback_router
from backend.api.routes.health import router as health_router
from backend.api.routes.me import router as me_router
from backend.api.routes.sessions import router as sessions_router
from backend.api.routes.traces import router as traces_router

app.include_router(chat_router, prefix="/api/v1")
app.include_router(health_router, prefix="/api/v1")
app.include_router(sessions_router, prefix="/api/v1")
app.include_router(feedback_router, prefix="/api/v1")
app.include_router(traces_router, prefix="/api/v1")
app.include_router(me_router, prefix="/api/v1")


@app.get("/", tags=["root"])
async def root():
    return {"message": "EPR Chatbot API is running. See /docs for the API reference."}


@app.get("/internal/metrics", tags=["metrics"])
async def metrics():
    """Prometheus metrics endpoint for the authenticated monitoring path."""
    return metrics_module.metrics_endpoint()

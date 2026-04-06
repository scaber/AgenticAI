import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from config import get_settings
from webhooks.handlers import router as webhook_router

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup / shutdown lifecycle."""
    settings = get_settings()
    logger.info(
        "app_starting",
        version="0.2.0",
        llm_provider=settings.llm_provider,
        repo_path=settings.git_repo_path,
    )
    yield
    logger.info("app_shutting_down")


app = FastAPI(
    title="AI PR Agent",
    description="AI-Powered Azure DevOps Agent: Autonomous PR Engine",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs" if get_settings().log_level.upper() == "DEBUG" else None,
    redoc_url=None,
)

# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Production'da kısıtla
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"],   # Production'da kısıtla
)

app.include_router(webhook_router)


@app.get("/")
async def root():
    return {
        "name": "AI PR Agent",
        "version": "0.2.0",
    }


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.log_level.lower(),
    )

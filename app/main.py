"""FastAPI application factory."""

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database.session import init_db
from app.utils.logging import setup_logging, get_logger
from app.scheduler.polling import start_scheduler, stop_scheduler
from app.api.auth import router as auth_router
from app.api.emails import router as emails_router
from app.api.drafts import router as drafts_router
from app.api.metrics import router as metrics_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Starting Email Reply Agent", env=settings.app_env)

    # Initialise database tables
    init_db()

    # Try to restore the last authenticated session
    _try_restore_session()

    # Start background polling scheduler
    start_scheduler(interval_seconds=settings.email_poll_interval_seconds)

    yield

    # Shutdown
    stop_scheduler()
    logger.info("Email Reply Agent shut down")


def _try_restore_session():
    """On startup, restore the most recently authenticated user's session."""
    try:
        from app.database.session import get_db_session
        from app.models.orm import UserRecord
        from app.services.auth_service import restore_session_from_db
        from app.services.dependencies import get_llm, get_memory_store
        from app.graph.workflow import EmailAgentGraph
        from app.services.email_service import register_graph
        from app.gmail.client import GmailClient

        with get_db_session() as db:
            user = db.query(UserRecord).order_by(UserRecord.updated_at.desc()).first()
            if user and user.google_access_token:
                ok = restore_session_from_db(user.email)
                if ok:
                    from app.services.auth_service import get_active_gmail_client
                    client = get_active_gmail_client()
                    graph = EmailAgentGraph(
                        llm=get_llm(),
                        gmail_client=client,
                        memory_store=get_memory_store(),
                        user_email=user.email,
                    )
                    register_graph(user.email, graph)
                    logger.info("Session restored on startup", user=user.email)
    except Exception as e:
        logger.warning("Could not restore session on startup", error=str(e))


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Email Reply Agent",
        description="Human-in-the-Loop AI Email Reply Agent",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(auth_router)
    app.include_router(emails_router)
    app.include_router(drafts_router)
    app.include_router(metrics_router)

    @app.get("/health")
    def health():
        from app.services.auth_service import is_authenticated, get_active_user_email
        from app.scheduler.polling import get_scheduler
        sched = get_scheduler()
        return {
            "status": "ok",
            "authenticated": is_authenticated(),
            "user": get_active_user_email(),
            "scheduler_running": sched.running if sched else False,
        }

    return app


app = create_app()

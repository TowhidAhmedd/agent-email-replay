"""APScheduler: background job that polls Gmail every N seconds."""

from __future__ import annotations

from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.utils.logging import get_logger

logger = get_logger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def _poll_job():
    """Called by APScheduler; imports lazily to avoid circular deps."""
    from app.services.email_service import get_graph, poll_and_process
    from app.services.auth_service import get_active_gmail_client

    client = get_active_gmail_client()
    if client is None:
        logger.debug("No active Gmail client — skipping poll")
        return

    # Use the registered graph for the active user
    from app.services.auth_service import get_active_user_email
    user_email = get_active_user_email()
    graph = get_graph(user_email) if user_email else None
    if graph is None:
        logger.debug("No active graph — skipping poll")
        return

    from app.config import get_settings
    settings = get_settings()
    processed = poll_and_process(client, graph, max_emails=settings.max_emails_per_poll)
    if processed:
        logger.info("Scheduler processed emails", count=len(processed), ids=processed)


def start_scheduler(interval_seconds: int = 60) -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _poll_job,
        trigger=IntervalTrigger(seconds=interval_seconds),
        id="email_poll",
        name="Gmail Inbox Poller",
        replace_existing=True,
        misfire_grace_time=30,
    )
    _scheduler.start()
    logger.info("Scheduler started", interval_seconds=interval_seconds)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def get_scheduler() -> Optional[BackgroundScheduler]:
    return _scheduler

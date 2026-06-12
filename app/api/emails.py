"""Email endpoints: list inbox, trigger processing."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.services.email_service import list_emails, get_email, poll_and_process, get_graph
from app.services.auth_service import get_active_gmail_client, get_active_user_email, is_authenticated
from app.utils.logging import get_logger

router = APIRouter(prefix="/emails", tags=["emails"])
logger = get_logger(__name__)


def _require_auth():
    if not is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated. Visit /auth/login")


@router.get("")
def get_emails(
    unread_only: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    _require_auth()
    emails = list_emails(db, skip=skip, limit=limit, unread_only=unread_only)
    return [
        {
            "id": e.id,
            "thread_id": e.thread_id,
            "subject": e.subject,
            "sender": e.sender,
            "sender_name": e.sender_name,
            "snippet": e.snippet,
            "email_date": e.email_date.isoformat() if e.email_date else None,
            "category": e.category,
            "priority": e.priority,
            "is_read": e.is_read,
            "labels": e.labels or [],
        }
        for e in emails
    ]


@router.get("/{email_id}")
def get_email_detail(email_id: str, db: Session = Depends(get_db)):
    _require_auth()
    email = get_email(db, email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    return {
        "id": email.id,
        "thread_id": email.thread_id,
        "subject": email.subject,
        "sender": email.sender,
        "sender_name": email.sender_name,
        "recipient": email.recipient,
        "body": email.body,
        "snippet": email.snippet,
        "email_date": email.email_date.isoformat() if email.email_date else None,
        "category": email.category,
        "priority": email.priority,
        "confidence_score": email.confidence_score,
        "is_read": email.is_read,
        "labels": email.labels or [],
        "attachments": email.attachments or [],
    }


@router.post("/poll")
def trigger_poll():
    """Manually trigger inbox polling."""
    _require_auth()
    client = get_active_gmail_client()
    user_email = get_active_user_email()
    graph = get_graph(user_email)
    if not graph:
        raise HTTPException(status_code=503, detail="Agent graph not initialised")
    from app.config import get_settings
    settings = get_settings()
    processed = poll_and_process(client, graph, max_emails=settings.max_emails_per_poll)
    return {"processed": processed, "count": len(processed)}


@router.post("/{email_id}/process")
def process_single_email(email_id: str):
    """Trigger workflow for a specific email ID."""
    _require_auth()
    user_email = get_active_user_email()
    graph = get_graph(user_email)
    if not graph:
        raise HTTPException(status_code=503, detail="Agent graph not initialised")
    state = graph.start_workflow(email_id)
    return {
        "workflow_run_id": state.get("workflow_run_id"),
        "status": state.get("workflow_status").value if hasattr(state.get("workflow_status"), "value") else state.get("workflow_status"),
        "draft_id": state.get("draft").id if state.get("draft") else None,
        "logs": state.get("logs", []),
        "errors": state.get("errors", []),
    }

"""Metrics and sent-emails endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.services.email_service import list_sent, get_metrics

router = APIRouter(tags=["analytics"])


@router.get("/metrics")
def get_agent_metrics(db: Session = Depends(get_db)):
    """Return aggregated agent analytics."""
    m = get_metrics(db)
    return m.model_dump()


@router.get("/sent")
def get_sent_emails(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List sent emails."""
    sent = list_sent(db, skip=skip, limit=limit)
    return [
        {
            "id": s.id,
            "draft_id": s.draft_id,
            "email_id": s.email_id,
            "gmail_message_id": s.gmail_message_id,
            "subject": s.subject,
            "recipient": s.recipient,
            "body_sent": s.body_sent,
            "sent_at": s.sent_at.isoformat() if s.sent_at else None,
        }
        for s in sent
    ]

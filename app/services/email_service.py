"""Email service: polls Gmail, triggers workflows, provides data to API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.orm import (
    EmailRecord, DraftRecord, ApprovalRecord,
    SentEmailRecord, WorkflowRun, AgentLog
)
from app.models.schemas import (
    EmailMessage, ApprovalDecision, ApprovalStatus, MetricsResponse
)
from app.gmail.client import GmailClient
from app.graph.workflow import EmailAgentGraph
from app.database.session import get_db_session
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Global graph registry: user_email → EmailAgentGraph
_graphs: Dict[str, EmailAgentGraph] = {}


def register_graph(user_email: str, graph: EmailAgentGraph) -> None:
    _graphs[user_email] = graph


def get_graph(user_email: str) -> Optional[EmailAgentGraph]:
    return _graphs.get(user_email)


# ─── Polling ────────────────────────────────────────────────────────────────────

def poll_and_process(gmail_client: GmailClient, graph: EmailAgentGraph, max_emails: int = 10) -> List[str]:
    """Fetch unread emails and kick off a workflow for each."""
    processed_ids = []
    try:
        messages = gmail_client.list_unread_messages(max_results=max_emails)
        logger.info("Polling inbox", unread_count=len(messages))

        for msg in messages:
            email_id = msg["id"]
            # Skip if already processed
            with get_db_session() as db:
                existing = db.query(WorkflowRun).filter(
                    WorkflowRun.email_id == email_id
                ).first()
                if existing:
                    continue

            logger.info("Processing new email", email_id=email_id)
            state = graph.start_workflow(email_id)
            processed_ids.append(email_id)

    except Exception as e:
        logger.error("Polling failed", error=str(e))

    return processed_ids


# ─── Data Access ────────────────────────────────────────────────────────────────

def list_emails(db: Session, skip: int = 0, limit: int = 50, unread_only: bool = False) -> List[EmailRecord]:
    q = db.query(EmailRecord).order_by(EmailRecord.email_date.desc())
    if unread_only:
        q = q.filter(EmailRecord.is_read == False)
    return q.offset(skip).limit(limit).all()


def get_email(db: Session, email_id: str) -> Optional[EmailRecord]:
    return db.query(EmailRecord).filter(EmailRecord.id == email_id).first()


def list_drafts(
    db: Session,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[DraftRecord]:
    q = db.query(DraftRecord).order_by(DraftRecord.generated_at.desc())
    if status:
        q = q.filter(DraftRecord.approval_status == status)
    return q.offset(skip).limit(limit).all()


def get_draft(db: Session, draft_id: str) -> Optional[DraftRecord]:
    return db.query(DraftRecord).filter(DraftRecord.id == draft_id).first()


def list_sent(db: Session, skip: int = 0, limit: int = 50) -> List[SentEmailRecord]:
    return (
        db.query(SentEmailRecord)
        .order_by(SentEmailRecord.sent_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_metrics(db: Session) -> MetricsResponse:
    total_emails = db.query(EmailRecord).count()
    total_drafts = db.query(DraftRecord).count()
    approved = db.query(DraftRecord).filter(
        DraftRecord.approval_status.in_(["approved", "sent"])
    ).count()
    rejected = db.query(DraftRecord).filter(
        DraftRecord.approval_status == "rejected"
    ).count()
    sent = db.query(SentEmailRecord).count()

    approval_rate = (approved / total_drafts * 100) if total_drafts else 0.0
    rejection_rate = (rejected / total_drafts * 100) if total_drafts else 0.0

    # Average processing time from workflow runs
    runs = db.query(WorkflowRun).filter(WorkflowRun.duration_seconds.isnot(None)).all()
    avg_time = sum(r.duration_seconds for r in runs) / len(runs) if runs else 0.0

    # By category
    from sqlalchemy import func
    cat_rows = db.query(EmailRecord.category, func.count()).group_by(EmailRecord.category).all()
    emails_by_category = {row[0] or "Unknown": row[1] for row in cat_rows}

    pri_rows = db.query(EmailRecord.priority, func.count()).group_by(EmailRecord.priority).all()
    emails_by_priority = {row[0] or "Unknown": row[1] for row in pri_rows}

    return MetricsResponse(
        total_emails_processed=total_emails,
        total_drafts_generated=total_drafts,
        approved_count=approved,
        rejected_count=rejected,
        sent_count=sent,
        approval_rate=round(approval_rate, 1),
        rejection_rate=round(rejection_rate, 1),
        avg_processing_time_seconds=round(avg_time, 2),
        emails_by_category=emails_by_category,
        emails_by_priority=emails_by_priority,
    )

"""Agent 7 — Send Email Agent: sends the approved reply via Gmail API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from app.gmail.client import GmailClient
from app.models.schemas import (
    AgentState, DraftReply, EmailMessage, ApprovalDecision, ApprovalStatus, WorkflowStatus
)
from app.database.session import get_db_session
from app.models.orm import DraftRecord, SentEmailRecord
from app.memory.store import MemoryStore
from app.utils.logging import get_logger

logger = get_logger(__name__)


def send_email_node(
    state: Dict[str, Any],
    gmail_client: GmailClient,
    memory_store: MemoryStore,
) -> Dict[str, Any]:
    """
    LangGraph node: send the approved draft via Gmail.
    ONLY executed when approval_decision.status == APPROVED.
    """
    email: EmailMessage | None = state.get("raw_email")
    draft: DraftReply | None = state.get("draft")
    decision: ApprovalDecision | None = state.get("approval_decision")
    logs = list(state.get("logs", []))

    # Safety gate — never send without explicit approval
    if not decision or decision.status != ApprovalStatus.APPROVED:
        error = "CRITICAL: send_email_node reached without approval — aborting"
        logger.error(error)
        return {
            **state,
            "errors": state.get("errors", []) + [error],
            "current_node": "send_email",
            "workflow_status": WorkflowStatus.FAILED,
            "logs": logs + [f"[send_email] {error}"],
        }

    if email is None or draft is None:
        return {
            **state,
            "errors": state.get("errors", []) + ["Missing email or draft for sending"],
            "current_node": "send_email",
            "workflow_status": WorkflowStatus.FAILED,
            "logs": logs,
        }

    # Use edited body if user modified it, otherwise use original draft
    body_to_send = decision.edited_body or draft.body
    logs.append(f"[send_email] Sending reply to {email.sender}")

    gmail_message_id = gmail_client.send_reply(
        to=email.sender,
        subject=email.subject,
        body=body_to_send,
        thread_id=email.thread_id,
    )

    if gmail_message_id is None:
        error = "Gmail send failed — message_id is None"
        logger.error(error, draft_id=draft.id)
        return {
            **state,
            "errors": state.get("errors", []) + [error],
            "current_node": "send_email",
            "workflow_status": WorkflowStatus.FAILED,
            "logs": logs + [f"[send_email] {error}"],
        }

    # Mark original email as read
    gmail_client.mark_as_read(email.id)

    # Persist sent record
    with get_db_session() as db:
        record = db.query(DraftRecord).filter(DraftRecord.id == draft.id).first()
        if record:
            record.approval_status = ApprovalStatus.SENT.value

        sent = SentEmailRecord(
            draft_id=draft.id,
            email_id=email.id,
            gmail_message_id=gmail_message_id,
            gmail_thread_id=email.thread_id,
            subject=email.subject,
            recipient=email.sender,
            body_sent=body_to_send,
            sent_at=datetime.utcnow(),
        )
        db.add(sent)

    # Store in ChromaDB memory for future context
    classification = state.get("classification")
    memory_store.store_approved_draft(
        draft_id=draft.id,
        email_category=classification.category.value if classification else "Other",
        original_subject=email.subject,
        approved_body=body_to_send,
    )
    memory_store.store_email_thread(
        thread_id=email.thread_id,
        subject=email.subject,
        participants=[email.sender, email.recipient],
        messages_summary=f"Subject: {email.subject}\nFrom: {email.sender}\n\nReply sent:\n{body_to_send[:500]}",
    )

    logs.append(f"[send_email] Email sent successfully. Gmail message_id={gmail_message_id}")
    logger.info("Email sent", gmail_message_id=gmail_message_id, draft_id=draft.id)

    return {
        **state,
        "current_node": "send_email",
        "workflow_status": WorkflowStatus.COMPLETED,
        "completed_at": datetime.utcnow(),
        "logs": logs,
    }


def archive_draft_node(state: Dict[str, Any], memory_store: MemoryStore) -> Dict[str, Any]:
    """LangGraph node: archive rejected draft."""
    draft: DraftReply | None = state.get("draft")
    decision: ApprovalDecision | None = state.get("approval_decision")
    logs = list(state.get("logs", []))

    reason = decision.reason if decision else "No reason provided"
    logs.append(f"[archive_draft] Draft rejected — reason: {reason}")
    logger.info("Draft archived/rejected", draft_id=draft.id if draft else None, reason=reason)

    return {
        **state,
        "current_node": "archive_draft",
        "workflow_status": WorkflowStatus.COMPLETED,
        "completed_at": datetime.utcnow(),
        "logs": logs,
    }

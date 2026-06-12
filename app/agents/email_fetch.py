"""Agent 1 — Email Fetch Agent: reads unread Gmail messages and persists them."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict

from app.gmail.client import GmailClient
from app.database.session import get_db_session
from app.models.orm import EmailRecord
from app.models.schemas import AgentState, EmailMessage
from app.utils.logging import get_logger

logger = get_logger(__name__)


def email_fetch_node(state: Dict[str, Any], gmail_client: GmailClient) -> Dict[str, Any]:
    """
    LangGraph node: fetch a single email by ID from Gmail and persist it.
    Expects state["email_id"] to be set.
    """
    email_id: str = state.get("email_id", "")
    logs = list(state.get("logs", []))

    if not email_id:
        logger.error("email_fetch_node called without email_id")
        return {**state, "errors": state.get("errors", []) + ["No email_id provided"], "current_node": "email_fetch"}

    logger.info("Fetching email", email_id=email_id)
    logs.append(f"[email_fetch] Fetching email {email_id}")

    email: EmailMessage | None = gmail_client.get_message(email_id)
    if email is None:
        return {
            **state,
            "errors": state.get("errors", []) + [f"Could not fetch email {email_id}"],
            "current_node": "email_fetch",
            "logs": logs,
        }

    # Persist to DB
    _upsert_email_record(email)
    logs.append(f"[email_fetch] Email persisted: subject='{email.subject}' from='{email.sender}'")

    logger.info("Email fetched", subject=email.subject, sender=email.sender)
    return {
        **state,
        "raw_email": email,
        "current_node": "email_fetch",
        "logs": logs,
    }


def _upsert_email_record(email: EmailMessage) -> None:
    with get_db_session() as db:
        existing = db.query(EmailRecord).filter(EmailRecord.id == email.id).first()
        if existing:
            return
        record = EmailRecord(
            id=email.id,
            thread_id=email.thread_id,
            subject=email.subject,
            sender=email.sender,
            sender_name=email.sender_name,
            recipient=email.recipient,
            body=email.body,
            body_html=email.body_html,
            snippet=email.snippet,
            email_date=email.date,
            labels=email.labels,
            attachments=email.attachments,
            is_read=email.is_read,
        )
        db.add(record)

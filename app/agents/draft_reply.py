"""Agent 4 — Draft Reply Agent: generates a professional email reply."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from app.models.schemas import (
    AgentState, DraftReply, EmailMessage, ClassificationResult, ContextResult
)
from app.database.session import get_db_session
from app.models.orm import DraftRecord
from app.utils.logging import get_logger

logger = get_logger(__name__)

DRAFT_SYSTEM = """You are an expert email assistant. Write a professional, context-aware reply.

Rules:
- Be concise, warm, and professional
- Address the sender by name if available
- Directly answer the email's main question or request
- Do NOT hallucinate facts or make promises you cannot confirm
- Do NOT reveal internal system details
- Sign off naturally without a placeholder name (use "Best regards," only)
- Return ONLY the email body text, no subject line, no metadata"""


def draft_reply_node(state: Dict[str, Any], llm: ChatGroq) -> Dict[str, Any]:
    """LangGraph node: generate a draft reply."""
    email: EmailMessage | None = state.get("raw_email")
    classification: ClassificationResult | None = state.get("classification")
    context: ContextResult | None = state.get("context")
    logs = list(state.get("logs", []))

    if email is None:
        return {**state, "errors": state.get("errors", []) + ["No email for drafting"], "current_node": "draft_reply"}

    logs.append("[draft_reply] Generating reply draft")

    # Build context block
    context_block = ""
    if context:
        if context.similar_responses:
            context_block += "\n\nSimilar approved responses for reference:\n"
            for r in context.similar_responses[:2]:
                context_block += f"---\n{r[:400]}\n"
        if context.previous_threads:
            context_block += "\n\nPrevious conversation context:\n"
            for t in context.previous_threads[:1]:
                context_block += f"Thread: {t.get('document', '')[:300]}\n"
        if context.user_preferences.get("writing_style"):
            context_block += f"\n\nUser writing style preference:\n{context.user_preferences['writing_style']}"

    category_hint = classification.category.value if classification else "General"
    priority_hint = classification.priority.value if classification else "medium"

    prompt = f"""Email category: {category_hint} | Priority: {priority_hint}

From: {email.sender_name or email.sender} <{email.sender}>
Subject: {email.subject}
Date: {email.date.strftime('%B %d, %Y')}

Email body:
{email.body[:2000]}
{context_block}

Write a professional reply to this email:"""

    try:
        response = llm.invoke([
            SystemMessage(content=DRAFT_SYSTEM),
            HumanMessage(content=prompt),
        ])
        body = response.content.strip()

        draft = DraftReply(
            id=str(uuid.uuid4()),
            email_id=email.id,
            thread_id=email.thread_id,
            subject=email.subject,
            body=body,
            confidence_score=0.85,
            generated_at=datetime.utcnow(),
            model_used=llm.model_name,
        )

        # Persist draft
        _persist_draft(draft)
        logs.append(f"[draft_reply] Draft generated (id={draft.id}, len={len(body)} chars)")
        logger.info("Draft generated", draft_id=draft.id, email_id=email.id)

        return {
            **state,
            "draft": draft,
            "current_node": "draft_reply",
            "logs": logs,
        }

    except Exception as e:
        logger.error("Draft generation failed", error=str(e))
        return {
            **state,
            "errors": state.get("errors", []) + [f"Draft generation failed: {str(e)}"],
            "current_node": "draft_reply",
            "logs": logs + [f"[draft_reply] Error: {str(e)}"],
        }


def _persist_draft(draft: DraftReply) -> None:
    with get_db_session() as db:
        record = DraftRecord(
            id=draft.id,
            email_id=draft.email_id,
            thread_id=draft.thread_id,
            subject=draft.subject,
            body=draft.body,
            confidence_score=draft.confidence_score,
            model_used=draft.model_used,
            approval_status="pending",
            generated_at=draft.generated_at,
        )
        db.add(record)

"""Agent 2 — Email Classification Agent: categorises and prioritises emails."""

from __future__ import annotations

import json
from typing import Any, Dict

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from app.models.schemas import (
    AgentState, ClassificationResult, EmailCategory, Priority, EmailMessage
)
from app.database.session import get_db_session
from app.models.orm import EmailRecord
from app.utils.logging import get_logger

logger = get_logger(__name__)

CLASSIFICATION_SYSTEM = """You are an expert email classifier. Analyze the email and return ONLY valid JSON.

Categories: Job Opportunity, Client Inquiry, Customer Support, Meeting Request, Follow Up, 
Partnership, Sales, Personal, Newsletter, Spam, Other

Priorities: critical, high, medium, low

Return exactly this JSON structure (no markdown, no extra text):
{
  "category": "<category>",
  "priority": "<priority>",
  "confidence_score": <0.0-1.0>,
  "reasoning": "<brief explanation>",
  "keywords": ["keyword1", "keyword2"]
}"""


def classification_node(state: Dict[str, Any], llm: ChatGroq) -> Dict[str, Any]:
    """LangGraph node: classify the email using the LLM."""
    email: EmailMessage | None = state.get("raw_email")
    logs = list(state.get("logs", []))

    if email is None:
        return {**state, "errors": state.get("errors", []) + ["No email to classify"], "current_node": "classification"}

    logs.append(f"[classification] Classifying email: '{email.subject}'")

    prompt = f"""From: {email.sender}
Subject: {email.subject}
Body:
{email.body[:1500]}"""

    try:
        response = llm.invoke([
            SystemMessage(content=CLASSIFICATION_SYSTEM),
            HumanMessage(content=prompt),
        ])
        raw = response.content.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)

        result = ClassificationResult(
            category=EmailCategory(data.get("category", "Other")),
            priority=Priority(data.get("priority", "medium")),
            confidence_score=float(data.get("confidence_score", 0.7)),
            reasoning=data.get("reasoning", ""),
            keywords=data.get("keywords", []),
        )

        # Persist to DB
        with get_db_session() as db:
            record = db.query(EmailRecord).filter(EmailRecord.id == email.id).first()
            if record:
                record.category = result.category.value
                record.priority = result.priority.value
                record.confidence_score = result.confidence_score

        logs.append(f"[classification] category={result.category.value} priority={result.priority.value} confidence={result.confidence_score:.2f}")
        logger.info("Email classified", category=result.category.value, priority=result.priority.value)

        return {
            **state,
            "classification": result,
            "current_node": "classification",
            "logs": logs,
        }

    except Exception as e:
        logger.error("Classification failed", error=str(e))
        # Fallback classification
        result = ClassificationResult(
            category=EmailCategory.OTHER,
            priority=Priority.MEDIUM,
            confidence_score=0.3,
            reasoning=f"Classification failed: {str(e)}",
        )
        return {
            **state,
            "classification": result,
            "current_node": "classification",
            "logs": logs + [f"[classification] Failed, using fallback: {str(e)}"],
        }

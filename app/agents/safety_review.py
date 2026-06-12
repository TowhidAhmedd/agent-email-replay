"""Agent 5 — Safety Review Agent: checks generated draft for risks before human review."""

from __future__ import annotations

import json
from typing import Any, Dict

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from app.models.schemas import (
    AgentState, DraftReply, EmailMessage, SafetyReview, SafetyFlag
)
from app.database.session import get_db_session
from app.models.orm import DraftRecord
from app.utils.logging import get_logger

logger = get_logger(__name__)

SAFETY_SYSTEM = """You are a safety auditor for AI-generated emails. Analyze the draft for risks.

Check for:
1. hallucination — claims that cannot be verified from the original email
2. incorrect_promise — commitments or guarantees the sender cannot make
3. sensitive_info — personal data, credentials, confidential details
4. aggressive_language — rude, threatening, or inappropriate tone
5. compliance_issue — legal, regulatory, or policy concerns

Return ONLY valid JSON (no markdown):
{
  "risk_score": <0.0-1.0>,
  "flags": ["flag1", "flag2"],
  "recommendations": ["rec1", "rec2"],
  "is_safe": <true|false>
}

flags must be from: hallucination, incorrect_promise, sensitive_info, aggressive_language, compliance_issue, clean
is_safe is false only if risk_score > 0.7"""


def safety_review_node(state: Dict[str, Any], llm: ChatGroq) -> Dict[str, Any]:
    """LangGraph node: run safety checks on the draft reply."""
    email: EmailMessage | None = state.get("raw_email")
    draft: DraftReply | None = state.get("draft")
    logs = list(state.get("logs", []))

    if draft is None:
        return {
            **state,
            "errors": state.get("errors", []) + ["No draft to review"],
            "current_node": "safety_review",
            "logs": logs,
        }

    logs.append("[safety_review] Running safety checks on draft")

    prompt = f"""Original email:
From: {email.sender if email else 'unknown'}
Subject: {email.subject if email else 'unknown'}
Body: {email.body[:800] if email else ''}

Draft reply to review:
{draft.body}

Analyze this draft for safety issues:"""

    try:
        response = llm.invoke([
            SystemMessage(content=SAFETY_SYSTEM),
            HumanMessage(content=prompt),
        ])
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)

        flags_raw = data.get("flags", ["clean"])
        flags = []
        for f in flags_raw:
            try:
                flags.append(SafetyFlag(f))
            except ValueError:
                flags.append(SafetyFlag.CLEAN)

        review = SafetyReview(
            risk_score=float(data.get("risk_score", 0.1)),
            flags=flags if flags else [SafetyFlag.CLEAN],
            recommendations=data.get("recommendations", []),
            is_safe=bool(data.get("is_safe", True)),
        )

        # Persist safety info to draft record
        with get_db_session() as db:
            record = db.query(DraftRecord).filter(DraftRecord.id == draft.id).first()
            if record:
                record.risk_score = review.risk_score
                record.safety_flags = [f.value for f in review.flags]
                record.safety_recommendations = review.recommendations

        logs.append(
            f"[safety_review] risk_score={review.risk_score:.2f} "
            f"is_safe={review.is_safe} flags={[f.value for f in review.flags]}"
        )
        logger.info("Safety review complete", risk_score=review.risk_score, is_safe=review.is_safe)

        return {
            **state,
            "safety_review": review,
            "current_node": "safety_review",
            "logs": logs,
        }

    except Exception as e:
        logger.error("Safety review failed", error=str(e))
        # Default to safe on failure so human can still review
        review = SafetyReview(
            risk_score=0.2,
            flags=[SafetyFlag.CLEAN],
            recommendations=[f"Automated safety check failed: {str(e)} — please review manually"],
            is_safe=True,
        )
        return {
            **state,
            "safety_review": review,
            "current_node": "safety_review",
            "logs": logs + [f"[safety_review] Error (defaulting safe): {str(e)}"],
        }

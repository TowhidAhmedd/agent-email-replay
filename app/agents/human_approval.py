"""Agent 6 — Human Approval Node: pauses the graph until a human approves/rejects."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from app.models.schemas import (
    AgentState, DraftReply, SafetyReview, ApprovalDecision, ApprovalStatus, WorkflowStatus
)
from app.database.session import get_db_session
from app.models.orm import DraftRecord, WorkflowRun
from app.utils.logging import get_logger

logger = get_logger(__name__)


def human_approval_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph interrupt node.
    This node sets status=WAITING_APPROVAL and returns.
    The graph runner detects this and suspends execution.
    Resumption happens via the API when the user approves/rejects.
    """
    draft: DraftReply | None = state.get("draft")
    logs = list(state.get("logs", []))
    run_id: str = state.get("workflow_run_id", "")

    if draft is None:
        return {
            **state,
            "errors": state.get("errors", []) + ["No draft available for approval"],
            "current_node": "human_approval",
            "workflow_status": WorkflowStatus.FAILED,
            "logs": logs,
        }

    logs.append(f"[human_approval] Workflow paused — awaiting human decision on draft {draft.id}")
    logger.info("Workflow paused for human approval", draft_id=draft.id, run_id=run_id)

    # Update workflow run status in DB
    if run_id:
        with get_db_session() as db:
            run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
            if run:
                run.status = WorkflowStatus.WAITING_APPROVAL.value
                run.current_node = "human_approval"

    return {
        **state,
        "current_node": "human_approval",
        "workflow_status": WorkflowStatus.WAITING_APPROVAL,
        "logs": logs,
    }


def apply_approval_decision(
    state: Dict[str, Any],
    decision: ApprovalDecision,
) -> Dict[str, Any]:
    """
    Called after the human has decided.
    Injects the ApprovalDecision into state so the graph can route to send or archive.
    """
    logs = list(state.get("logs", []))
    draft: DraftReply | None = state.get("draft")

    logs.append(f"[human_approval] Decision received: {decision.status.value}")

    # If user edited the body, update the draft object
    if draft and decision.edited_body:
        draft = draft.model_copy(update={"edited_body": decision.edited_body})
        logs.append("[human_approval] Draft body was edited by user")

    # Persist approval status to draft record
    if draft:
        with get_db_session() as db:
            record = db.query(DraftRecord).filter(DraftRecord.id == draft.id).first()
            if record:
                record.approval_status = decision.status.value
                record.decided_at = datetime.utcnow()
                if decision.status == ApprovalStatus.REJECTED:
                    record.rejection_reason = decision.reason
                if decision.edited_body:
                    record.edited_body = decision.edited_body

    logger.info("Approval decision applied", status=decision.status.value, draft_id=draft.id if draft else None)

    return {
        **state,
        "draft": draft,
        "approval_decision": decision,
        "current_node": "human_approval",
        "workflow_status": WorkflowStatus.RUNNING,
        "logs": logs,
    }


def should_send(state: Dict[str, Any]) -> str:
    """LangGraph conditional edge: route to send_email or archive_draft."""
    decision: ApprovalDecision | None = state.get("approval_decision")
    if decision and decision.status == ApprovalStatus.APPROVED:
        return "send_email"
    return "archive_draft"

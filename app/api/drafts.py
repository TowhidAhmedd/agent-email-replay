"""Draft endpoints: list drafts, approve/edit/reject, send."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.services.email_service import list_drafts, get_draft, get_graph
from app.services.auth_service import get_active_user_email, is_authenticated
from app.models.schemas import ApproveRequest, RejectRequest, ApprovalDecision, ApprovalStatus
from app.models.orm import DraftRecord, ApprovalRecord
from app.utils.logging import get_logger

router = APIRouter(prefix="/drafts", tags=["drafts"])
logger = get_logger(__name__)


def _require_auth():
    if not is_authenticated():
        raise HTTPException(status_code=401, detail="Not authenticated. Visit /auth/login")


def _draft_to_dict(d: DraftRecord) -> dict:
    return {
        "id": d.id,
        "email_id": d.email_id,
        "thread_id": d.thread_id,
        "subject": d.subject,
        "body": d.body,
        "edited_body": d.edited_body,
        "confidence_score": d.confidence_score,
        "model_used": d.model_used,
        "approval_status": d.approval_status,
        "risk_score": d.risk_score,
        "safety_flags": d.safety_flags or [],
        "safety_recommendations": d.safety_recommendations or [],
        "generated_at": d.generated_at.isoformat() if d.generated_at else None,
        "decided_at": d.decided_at.isoformat() if d.decided_at else None,
        "rejection_reason": d.rejection_reason,
    }


@router.get("")
def get_drafts(
    status: Optional[str] = Query(None, description="Filter by status: pending, approved, rejected, sent"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    _require_auth()
    drafts = list_drafts(db, status=status, skip=skip, limit=limit)
    return [_draft_to_dict(d) for d in drafts]


@router.get("/{draft_id}")
def get_draft_detail(draft_id: str, db: Session = Depends(get_db)):
    _require_auth()
    draft = get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return _draft_to_dict(draft)


@router.post("/approve/{draft_id}")
def approve_draft(draft_id: str, req: ApproveRequest, db: Session = Depends(get_db)):
    """Approve (and optionally edit) a draft — triggers email sending."""
    _require_auth()
    draft = get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.approval_status not in ("pending", "edited"):
        raise HTTPException(status_code=409, detail=f"Draft already {draft.approval_status}")

    user_email = get_active_user_email()
    graph = get_graph(user_email)
    if not graph:
        raise HTTPException(status_code=503, detail="Agent graph not initialised")

    # Find the suspended workflow for this draft's email
    run_id = _find_run_id_for_draft(db, draft)
    if not run_id:
        raise HTTPException(status_code=404, detail="No suspended workflow found for this draft")

    decision = ApprovalDecision(
        draft_id=draft_id,
        status=ApprovalStatus.APPROVED,
        edited_body=req.edited_body,
        reason=req.reason,
    )

    state = graph.resume_workflow(run_id, decision)

    # Persist approval record
    approval = ApprovalRecord(
        draft_id=draft_id,
        email_id=draft.email_id,
        status=ApprovalStatus.APPROVED.value,
        edited_body=req.edited_body,
        reason=req.reason,
    )
    db.add(approval)
    db.commit()

    return {
        "message": "Draft approved and email sent" if not state.get("errors") else "Approved but send failed",
        "workflow_status": state.get("workflow_status").value if hasattr(state.get("workflow_status"), "value") else state.get("workflow_status"),
        "errors": state.get("errors", []),
    }


@router.post("/reject/{draft_id}")
def reject_draft(draft_id: str, req: RejectRequest, db: Session = Depends(get_db)):
    """Reject a draft — archives it without sending."""
    _require_auth()
    draft = get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.approval_status not in ("pending", "edited"):
        raise HTTPException(status_code=409, detail=f"Draft already {draft.approval_status}")

    user_email = get_active_user_email()
    graph = get_graph(user_email)
    if not graph:
        raise HTTPException(status_code=503, detail="Agent graph not initialised")

    run_id = _find_run_id_for_draft(db, draft)
    if not run_id:
        # Still mark as rejected even without a running workflow
        draft.approval_status = ApprovalStatus.REJECTED.value
        draft.rejection_reason = req.reason
        db.commit()
        return {"message": "Draft rejected"}

    decision = ApprovalDecision(
        draft_id=draft_id,
        status=ApprovalStatus.REJECTED,
        reason=req.reason,
    )
    graph.resume_workflow(run_id, decision)

    approval = ApprovalRecord(
        draft_id=draft_id,
        email_id=draft.email_id,
        status=ApprovalStatus.REJECTED.value,
        reason=req.reason,
    )
    db.add(approval)
    db.commit()

    return {"message": "Draft rejected and archived"}


def _find_run_id_for_draft(db: Session, draft: DraftRecord) -> Optional[str]:
    from app.models.orm import WorkflowRun
    run = (
        db.query(WorkflowRun)
        .filter(
            WorkflowRun.email_id == draft.email_id,
            WorkflowRun.status == "waiting_approval",
        )
        .order_by(WorkflowRun.started_at.desc())
        .first()
    )
    return run.id if run else None

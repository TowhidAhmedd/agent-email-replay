"""Unit tests for agent nodes using mocked dependencies."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from app.models.schemas import (
    EmailMessage, ClassificationResult, EmailCategory, Priority,
    DraftReply, SafetyReview, SafetyFlag, ApprovalDecision, ApprovalStatus
)


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_email():
    return EmailMessage(
        id="msg_001",
        thread_id="thread_001",
        subject="Partnership Inquiry",
        sender="alice@example.com",
        sender_name="Alice Smith",
        recipient="me@mycompany.com",
        body="Hi, I'd like to discuss a potential partnership opportunity. Could we schedule a call?",
        date=datetime.utcnow(),
    )


@pytest.fixture
def base_state(sample_email):
    return {
        "email_id": "msg_001",
        "raw_email": sample_email,
        "classification": None,
        "context": None,
        "draft": None,
        "safety_review": None,
        "approval_decision": None,
        "workflow_run_id": "run_001",
        "workflow_status": "running",
        "current_node": "start",
        "errors": [],
        "logs": [],
        "started_at": datetime.utcnow(),
        "completed_at": None,
    }


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    return llm


# ─── Email Fetch ────────────────────────────────────────────────────────────────

class TestEmailFetchNode:
    def test_fetch_success(self, base_state, sample_email):
        from app.agents.email_fetch import email_fetch_node
        mock_client = MagicMock()
        mock_client.get_message.return_value = sample_email

        with patch("app.agents.email_fetch.get_db_session") as mock_db:
            mock_db.return_value.__enter__ = MagicMock(return_value=MagicMock(
                query=MagicMock(return_value=MagicMock(
                    filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
                )),
                add=MagicMock(),
            ))
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            result = email_fetch_node(base_state, mock_client)

        assert result["raw_email"] == sample_email
        assert result["current_node"] == "email_fetch"
        assert "email_fetch" in " ".join(result["logs"])

    def test_fetch_no_email_id(self, base_state):
        from app.agents.email_fetch import email_fetch_node
        state = {**base_state, "email_id": ""}
        mock_client = MagicMock()
        result = email_fetch_node(state, mock_client)
        assert len(result["errors"]) > 0

    def test_fetch_gmail_returns_none(self, base_state):
        from app.agents.email_fetch import email_fetch_node
        mock_client = MagicMock()
        mock_client.get_message.return_value = None
        result = email_fetch_node(base_state, mock_client)
        assert len(result["errors"]) > 0


# ─── Classification ─────────────────────────────────────────────────────────────

class TestClassificationNode:
    def test_classify_success(self, base_state, mock_llm):
        from app.agents.classification import classification_node
        mock_llm.invoke.return_value = MagicMock(
            content='{"category": "Partnership", "priority": "high", "confidence_score": 0.9, "reasoning": "test", "keywords": ["partnership"]}'
        )

        with patch("app.agents.classification.get_db_session") as mock_db:
            mock_db.return_value.__enter__ = MagicMock(return_value=MagicMock(
                query=MagicMock(return_value=MagicMock(
                    filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
                ))
            ))
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            result = classification_node(base_state, mock_llm)

        assert result["classification"] is not None
        assert result["classification"].category == EmailCategory.PARTNERSHIP
        assert result["classification"].priority == Priority.HIGH

    def test_classify_no_email(self, base_state, mock_llm):
        from app.agents.classification import classification_node
        state = {**base_state, "raw_email": None}
        result = classification_node(state, mock_llm)
        assert len(result["errors"]) > 0

    def test_classify_llm_fallback(self, base_state, mock_llm):
        from app.agents.classification import classification_node
        mock_llm.invoke.side_effect = Exception("LLM error")
        result = classification_node(base_state, mock_llm)
        # Should fallback, not crash
        assert result["classification"] is not None
        assert result["classification"].category == EmailCategory.OTHER


# ─── Safety Review ──────────────────────────────────────────────────────────────

class TestSafetyReviewNode:
    def test_safety_clean(self, base_state, mock_llm, sample_email):
        from app.agents.safety_review import safety_review_node
        from app.models.schemas import DraftReply

        draft = DraftReply(
            id="draft_001",
            email_id="msg_001",
            thread_id="thread_001",
            subject="Re: Partnership Inquiry",
            body="Thank you for reaching out! I'd be happy to discuss a partnership.",
            confidence_score=0.9,
        )
        state = {**base_state, "draft": draft}

        mock_llm.invoke.return_value = MagicMock(
            content='{"risk_score": 0.05, "flags": ["clean"], "recommendations": [], "is_safe": true}'
        )

        with patch("app.agents.safety_review.get_db_session") as mock_db:
            mock_db.return_value.__enter__ = MagicMock(return_value=MagicMock(
                query=MagicMock(return_value=MagicMock(
                    filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
                ))
            ))
            mock_db.return_value.__exit__ = MagicMock(return_value=False)

            result = safety_review_node(state, mock_llm)

        assert result["safety_review"] is not None
        assert result["safety_review"].is_safe is True
        assert result["safety_review"].risk_score < 0.5

    def test_safety_no_draft(self, base_state, mock_llm):
        from app.agents.safety_review import safety_review_node
        state = {**base_state, "draft": None}
        result = safety_review_node(state, mock_llm)
        assert len(result["errors"]) > 0


# ─── Human Approval ─────────────────────────────────────────────────────────────

class TestHumanApprovalNode:
    def test_approval_pauses_workflow(self, base_state):
        from app.agents.human_approval import human_approval_node
        from app.models.schemas import DraftReply, WorkflowStatus

        draft = DraftReply(
            id="draft_001", email_id="msg_001", thread_id="thread_001",
            subject="Re: Test", body="Hello!", confidence_score=0.9,
        )
        state = {**base_state, "draft": draft}

        with patch("app.agents.human_approval.get_db_session") as mock_db:
            mock_db.return_value.__enter__ = MagicMock(return_value=MagicMock(
                query=MagicMock(return_value=MagicMock(
                    filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
                ))
            ))
            mock_db.return_value.__exit__ = MagicMock(return_value=False)
            result = human_approval_node(state)

        assert result["workflow_status"] == WorkflowStatus.WAITING_APPROVAL

    def test_should_send_approved(self, base_state):
        from app.agents.human_approval import should_send

        decision = ApprovalDecision(
            draft_id="draft_001",
            status=ApprovalStatus.APPROVED,
        )
        state = {**base_state, "approval_decision": decision}
        assert should_send(state) == "send_email"

    def test_should_send_rejected(self, base_state):
        from app.agents.human_approval import should_send

        decision = ApprovalDecision(
            draft_id="draft_001",
            status=ApprovalStatus.REJECTED,
        )
        state = {**base_state, "approval_decision": decision}
        assert should_send(state) == "archive_draft"

    def test_never_sends_without_approval(self, base_state):
        from app.agents.human_approval import should_send
        state = {**base_state, "approval_decision": None}
        assert should_send(state) == "archive_draft"

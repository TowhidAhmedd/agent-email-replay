"""
LangGraph stateful workflow for the email reply agent.

Flow:
  email_fetch → classification → context_retrieval → draft_reply
  → safety_review → human_approval → [send_email | archive_draft] → END

The graph is designed to be interruptible at human_approval.
External code (API layer) resumes the graph by calling resume_workflow().
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq

from app.models.schemas import AgentState, WorkflowStatus, ApprovalDecision
from app.agents.human_approval import apply_approval_decision, should_send
from app.gmail.client import GmailClient
from app.memory.store import MemoryStore
from app.database.session import get_db_session
from app.models.orm import WorkflowRun, AgentLog
from app.utils.logging import get_logger

logger = get_logger(__name__)


class EmailAgentGraph:
    """Manages the LangGraph workflow lifecycle."""

    def __init__(
        self,
        llm: ChatGroq,
        gmail_client: GmailClient,
        memory_store: MemoryStore,
        user_email: str = "",
    ):
        self.llm = llm
        self.gmail_client = gmail_client
        self.memory_store = memory_store
        self.user_email = user_email
        self._graph = self._build_graph()

        # In-memory store for interrupted states (keyed by workflow_run_id)
        self._suspended: Dict[str, Dict[str, Any]] = {}

    # ─── Graph Construction ─────────────────────────────────────────────────────

    def _build_graph(self):
        from app.agents.email_fetch import email_fetch_node
        from app.agents.classification import classification_node
        from app.agents.context_retrieval import context_retrieval_node
        from app.agents.draft_reply import draft_reply_node
        from app.agents.safety_review import safety_review_node
        from app.agents.human_approval import human_approval_node
        from app.agents.send_email import send_email_node, archive_draft_node

        # Bind dependencies into each node
        def fetch(state):
            return self._timed_node("email_fetch", state, email_fetch_node, self.gmail_client)

        def classify(state):
            return self._timed_node("classification", state, classification_node, self.llm)

        def retrieve(state):
            return self._timed_node(
                "context_retrieval", state, context_retrieval_node,
                self.memory_store, self.user_email
            )

        def draft(state):
            return self._timed_node("draft_reply", state, draft_reply_node, self.llm)

        def safety(state):
            return self._timed_node("safety_review", state, safety_review_node, self.llm)

        def approval(state):
            return self._timed_node("human_approval", state, human_approval_node)

        def send(state):
            return self._timed_node(
                "send_email", state, send_email_node,
                self.gmail_client, self.memory_store
            )

        def archive(state):
            return self._timed_node(
                "archive_draft", state, archive_draft_node, self.memory_store
            )

        builder = StateGraph(dict)

        builder.add_node("email_fetch", fetch)
        builder.add_node("classification", classify)
        builder.add_node("context_retrieval", retrieve)
        builder.add_node("draft_reply", draft)
        builder.add_node("safety_review", safety)
        builder.add_node("human_approval", approval)
        builder.add_node("send_email", send)
        builder.add_node("archive_draft", archive)

        builder.set_entry_point("email_fetch")
        builder.add_edge("email_fetch", "classification")
        builder.add_edge("classification", "context_retrieval")
        builder.add_edge("context_retrieval", "draft_reply")
        builder.add_edge("draft_reply", "safety_review")
        builder.add_edge("safety_review", "human_approval")

        # human_approval suspends; resumption is handled externally
        builder.add_edge("human_approval", END)
        builder.add_edge("send_email", END)
        builder.add_edge("archive_draft", END)

        return builder.compile()

    # ─── Execution ──────────────────────────────────────────────────────────────

    def start_workflow(self, email_id: str) -> Dict[str, Any]:
        """
        Run the graph up to human_approval, then suspend.
        Returns the final state dict.
        """
        run_id = str(uuid.uuid4())
        initial_state: Dict[str, Any] = {
            "email_id": email_id,
            "raw_email": None,
            "classification": None,
            "context": None,
            "draft": None,
            "safety_review": None,
            "approval_decision": None,
            "workflow_run_id": run_id,
            "workflow_status": WorkflowStatus.RUNNING,
            "current_node": "start",
            "errors": [],
            "logs": [],
            "started_at": datetime.utcnow(),
            "completed_at": None,
        }

        # Persist run record
        self._create_run_record(run_id, email_id)

        logger.info("Starting workflow", run_id=run_id, email_id=email_id)
        try:
            final_state = self._graph.invoke(initial_state)
        except Exception as e:
            logger.error("Workflow failed", run_id=run_id, error=str(e))
            final_state = {**initial_state, "errors": [str(e)], "workflow_status": WorkflowStatus.FAILED}

        # If paused at approval, store state for resumption
        if final_state.get("workflow_status") == WorkflowStatus.WAITING_APPROVAL:
            self._suspended[run_id] = final_state
            logger.info("Workflow suspended at human_approval", run_id=run_id)

        self._update_run_record(run_id, final_state)
        return final_state

    def resume_workflow(self, run_id: str, decision: ApprovalDecision) -> Dict[str, Any]:
        """
        Resume a suspended workflow after a human decision.
        Runs send_email or archive_draft based on the decision.
        """
        if run_id not in self._suspended:
            raise ValueError(f"No suspended workflow found for run_id={run_id}")

        state = self._suspended.pop(run_id)
        state = apply_approval_decision(state, decision)

        route = should_send(state)
        logger.info("Resuming workflow", run_id=run_id, route=route)

        if route == "send_email":
            from app.agents.send_email import send_email_node
            state = self._timed_node(
                "send_email", state, send_email_node,
                self.gmail_client, self.memory_store
            )
        else:
            from app.agents.send_email import archive_draft_node
            state = self._timed_node(
                "archive_draft", state, archive_draft_node, self.memory_store
            )

        self._update_run_record(run_id, state)
        return state

    def get_suspended_state(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self._suspended.get(run_id)

    # ─── Helpers ────────────────────────────────────────────────────────────────

    def _timed_node(self, node_name: str, state: Dict[str, Any], fn, *args) -> Dict[str, Any]:
        """Wrap a node with timing and logging."""
        start = datetime.utcnow()
        try:
            result = fn(state, *args) if args else fn(state)
            duration = (datetime.utcnow() - start).total_seconds()
            self._log_node(
                run_id=state.get("workflow_run_id", ""),
                email_id=state.get("email_id", ""),
                node_name=node_name,
                status="success",
                duration=duration,
            )
            return result
        except Exception as e:
            duration = (datetime.utcnow() - start).total_seconds()
            self._log_node(
                run_id=state.get("workflow_run_id", ""),
                email_id=state.get("email_id", ""),
                node_name=node_name,
                status="error",
                duration=duration,
                error=str(e),
            )
            raise

    def _create_run_record(self, run_id: str, email_id: str) -> None:
        with get_db_session() as db:
            run = WorkflowRun(
                id=run_id,
                email_id=email_id,
                status=WorkflowStatus.RUNNING.value,
                current_node="start",
                started_at=datetime.utcnow(),
            )
            db.add(run)

    def _update_run_record(self, run_id: str, state: Dict[str, Any]) -> None:
        with get_db_session() as db:
            run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
            if run:
                status = state.get("workflow_status", WorkflowStatus.RUNNING)
                run.status = status.value if hasattr(status, "value") else str(status)
                run.current_node = state.get("current_node", "")
                completed_at = state.get("completed_at")
                if completed_at:
                    run.completed_at = completed_at
                    run.duration_seconds = (completed_at - run.started_at).total_seconds()
                errors = state.get("errors", [])
                if errors:
                    run.error_message = "; ".join(errors)

    def _log_node(
        self, run_id: str, email_id: str, node_name: str,
        status: str, duration: float, error: str = ""
    ) -> None:
        try:
            with get_db_session() as db:
                log = AgentLog(
                    workflow_run_id=run_id,
                    email_id=email_id or None,
                    node_name=node_name,
                    status=status,
                    duration_seconds=duration,
                    error_message=error or None,
                )
                db.add(log)
        except Exception:
            pass  # Never crash the workflow due to logging

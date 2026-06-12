"""Agent 3 — Context Retrieval Agent: fetches relevant memory from ChromaDB."""

from __future__ import annotations

from typing import Any, Dict

from app.memory.store import MemoryStore
from app.models.schemas import AgentState, ContextResult, EmailMessage, ClassificationResult
from app.utils.logging import get_logger

logger = get_logger(__name__)


def context_retrieval_node(
    state: Dict[str, Any],
    memory_store: MemoryStore,
    user_email: str = "",
) -> Dict[str, Any]:
    """LangGraph node: retrieve relevant context from memory."""
    email: EmailMessage | None = state.get("raw_email")
    classification: ClassificationResult | None = state.get("classification")
    logs = list(state.get("logs", []))

    if email is None:
        return {**state, "errors": state.get("errors", []) + ["No email for context"], "current_node": "context_retrieval"}

    logs.append("[context_retrieval] Retrieving relevant context from memory")

    query = f"{email.subject} {email.body[:500]}"
    category_str = classification.category.value if classification else ""

    # Retrieve similar threads
    similar_threads = memory_store.retrieve_similar_threads(query, n_results=3)

    # Retrieve similar approved responses
    similar_responses = memory_store.retrieve_similar_responses(query, category=category_str, n_results=3)

    # Retrieve company knowledge
    company_knowledge = memory_store.retrieve_knowledge(query, n_results=2)

    # Get writing style
    writing_style = memory_store.get_writing_style(user_email) if user_email else ""

    user_preferences: Dict[str, Any] = {}
    if writing_style:
        user_preferences["writing_style"] = writing_style

    company_info: Dict[str, Any] = {}
    if company_knowledge:
        company_info["knowledge_snippets"] = company_knowledge

    context = ContextResult(
        previous_threads=similar_threads,
        user_preferences=user_preferences,
        similar_responses=similar_responses,
        company_info=company_info,
    )

    logs.append(
        f"[context_retrieval] Found {len(similar_threads)} threads, "
        f"{len(similar_responses)} responses, {len(company_knowledge)} knowledge items"
    )
    logger.info("Context retrieved", threads=len(similar_threads), responses=len(similar_responses))

    return {
        **state,
        "context": context,
        "current_node": "context_retrieval",
        "logs": logs,
    }

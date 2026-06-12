"""
FastAPI dependency injection container.
Provides shared LLM, Gmail client, memory store, and graph instances.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from langchain_groq import ChatGroq

from app.config import get_settings
from app.memory.store import MemoryStore
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Singletons
_memory_store: Optional[MemoryStore] = None
_llm: Optional[ChatGroq] = None


def get_llm() -> ChatGroq:
    global _llm
    if _llm is None:
        settings = get_settings()
        _llm = ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            temperature=0.3,
            max_tokens=2048,
        )
        logger.info("LLM initialised", model=settings.groq_model)
    return _llm


def get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        settings = get_settings()
        _memory_store = MemoryStore(persist_dir=settings.chroma_persist_dir)
        logger.info("MemoryStore initialised", dir=settings.chroma_persist_dir)
    return _memory_store


# Gmail client is per-user (tied to OAuth tokens), so it lives in the session service
# The graph factory is created per-user-session in the service layer

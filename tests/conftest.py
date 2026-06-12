"""Pytest configuration."""
import os
import pytest

# Set test environment variables before any imports
os.environ.setdefault("GROQ_API_KEY", "test_groq_key")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test_client_id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("SECRET_KEY", "test_secret_key_32_characters_xxx")
os.environ.setdefault("LANGCHAIN_API_KEY", "test_ls_key")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/sqlite/test_email_agent.db")
os.environ.setdefault("APP_ENV", "test")

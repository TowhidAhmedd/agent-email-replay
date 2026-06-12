"""Central configuration loaded from environment variables."""

from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # LLM
    groq_api_key: str = Field(..., env="GROQ_API_KEY")
    groq_model: str = Field("llama-3.3-70b-versatile", env="GROQ_MODEL")

    # LangSmith
    langchain_tracing_v2: str = Field("true", env="LANGCHAIN_TRACING_V2")
    langchain_api_key: str = Field("", env="LANGCHAIN_API_KEY")
    langchain_project: str = Field("email-reply-agent", env="LANGCHAIN_PROJECT")

    # Google OAuth / Gmail
    google_client_id: str = Field(..., env="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(..., env="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field("http://localhost:8000/auth/callback", env="GOOGLE_REDIRECT_URI")

    # Database
    database_url: str = Field("sqlite:///./data/sqlite/email_agent.db", env="DATABASE_URL")

    # ChromaDB
    chroma_persist_dir: str = Field("./data/chroma", env="CHROMA_PERSIST_DIR")

    # App
    secret_key: str = Field(..., env="SECRET_KEY")
    app_env: str = Field("production", env="APP_ENV")
    log_level: str = Field("INFO", env="LOG_LEVEL")
    api_host: str = Field("0.0.0.0", env="API_HOST")
    api_port: int = Field(8000, env="API_PORT")

    # Scheduler
    email_poll_interval_seconds: int = Field(60, env="EMAIL_POLL_INTERVAL_SECONDS")
    max_emails_per_poll: int = Field(10, env="MAX_EMAILS_PER_POLL")

    # Streamlit
    streamlit_api_base_url: str = Field("http://localhost:8000", env="STREAMLIT_API_BASE_URL")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

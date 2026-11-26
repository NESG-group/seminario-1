from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings managed via environment variables."""

    project_name: str = "NOMS 2027 demo"
    api_v1_prefix: str = "/v1"

    # Database (PostgreSQL + pgvector)
    database_url: str = "postgresql+asyncpg://demo:demo_pass@localhost:5432/demo_db"
    db_echo: bool = False

    hermes_base_url: str = "http://localhost:8642/v1"
    hermes_api_key: str = "change-me"
    # A tool-using answer can take minutes, plus the wait for earlier chats (one at a time).
    hermes_timeout_s: float = 600.0
    default_llm_model: str = "qwen2.5:72b"

    # Multi-user mode: secret Open WebUI signs the forwarded user JWT with
    # (FORWARD_USER_INFO_HEADER_JWT_SECRET). Unset or empty = single user.
    user_jwt_secret: str | None = None

    # Datalake pcap staging
    pcap_staging_root: Path = Path("/var/lib/demo/pcap_staging")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

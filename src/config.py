"""환경변수 로드 및 설정 객체."""

from __future__ import annotations

from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """애플리케이션 설정."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    tour_api_key: str = Field(alias="TOUR_API_KEY")

    db_host: str = Field(alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(alias="DB_NAME")
    db_user: str = Field(alias="DB_USER")
    db_password: str = Field(alias="DB_PASSWORD")

    openai_api_key: str = Field(alias="OPENAI_API_KEY")

    daily_api_call_limit: int = Field(default=900, alias="DAILY_API_CALL_LIMIT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def sqlalchemy_database_uri(self) -> str:
        """SQLAlchemy DSN 문자열."""
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """싱글턴 설정 객체 반환."""
    return Settings()

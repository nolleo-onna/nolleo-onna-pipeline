"""환경변수 → Settings 단일 진입점.

[원칙]
- .env의 키 형식(DB_HOST 등)을 진실의 원천으로 본다.
- 코드 내 다른 모든 모듈은 os.getenv()를 직접 부르지 말고 get_settings()를 거친다.
- @lru_cache로 싱글턴화 → 호출 비용 0, 테스트에서 cache_clear()로 리셋 가능.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """파이프라인 런타임 설정.

    Field(alias="...")로 .env 키와 1:1 매핑.
    누락된 필수값(alias 매칭 실패)은 인스턴스 생성 시 즉시 ValidationError로 멈춤.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,   # .env 키는 대소문자 정확히 일치해야 함
        extra="ignore",        # .env에 정의되지 않은 키 무시
    )

    # ── 외부 API ──────────────────────────────────────
    tour_api_key: str = Field(alias="TOUR_API_KEY")
    openai_api_key: str = Field(alias="OPENAI_API_KEY")

    # ── DB (분리 필드, .env와 일치) ──────────────────
    db_host: str = Field(alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(alias="DB_NAME")
    db_user: str = Field(alias="DB_USER")
    db_password: str = Field(alias="DB_PASSWORD")

    # ── 모델 / 운영 ───────────────────────────────────
    openai_embedding_model: str = Field(
        default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL"
    )
    openai_llm_model: str = Field(
        default="gpt-4o-mini", alias="OPENAI_LLM_MODEL"
    )
    daily_api_call_limit: int = Field(default=900, alias="DAILY_API_CALL_LIMIT")
    # ── 비활성 안전 가드 (ADR 0003) ────────────────────
    spots_deactivate_max_failure_rate: float = Field(
        default=0.05, alias="SPOTS_DEACTIVATE_MAX_FAILURE_RATE"
    )
    spots_deactivate_max_ratio: float = Field(
        default=0.2, alias="SPOTS_DEACTIVATE_MAX_RATIO"
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    env: str = Field(default="dev", alias="ENV")

    # ── 혼잡도 캐시 갱신 가드 (ADR 0003 패턴 재사용) ──
    spots_congestion_max_null_ratio: float = Field(
        default=0.3, alias="SPOTS_CONGESTION_MAX_NULL_RATIO"
    )

    # ── 파생 DSN (psycopg / SQLAlchemy 각각) ─────────
    @property
    def psycopg_dsn(self) -> str:
        """psycopg 드라이버용 DSN. common/db.py가 사용."""
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def sqlalchemy_database_uri(self) -> str:
        """SQLAlchemy/Alembic 용 URI. alembic/env.py가 사용."""
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """싱글턴 Settings. 첫 호출 때 .env 읽고 이후엔 캐시.

    테스트에서 .env를 갈아끼울 땐 `get_settings.cache_clear()` 호출 후 재호출.
    """
    return Settings()
"""환경변수 설정 로더."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """파이프라인 런타임 설정."""

    database_url: str
    tour_api_key: str
    openai_api_key: str
    kakao_rest_api_key: str
    kma_api_key: str
    busan_goodprice_api_key: str
    log_level: str = "INFO"
    env: str = "dev"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_llm_model: str = "gpt-4o-mini"

    class Config:
        env_file = ".env"


def get_settings() -> Settings:
    """설정 인스턴스를 반환한다."""
    raise NotImplementedError


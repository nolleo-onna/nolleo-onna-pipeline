from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    database_url: str = Field(alias="DATABASE_URL")
    tour_api_key: str = Field(alias="TOUR_API_KEY")
    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    kakao_rest_api_key: str = Field(alias="KAKAO_REST_API_KEY")
    kma_api_key: str = Field(alias="KMA_API_KEY")
    busan_goodprice_api_key: str = Field(alias="BUSAN_GOODPRICE_API_KEY")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    env: Literal["dev", "prod"] = Field(default="dev", alias="ENV")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


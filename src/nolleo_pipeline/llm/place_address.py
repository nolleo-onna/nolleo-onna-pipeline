"""음식 장소 주소 추론 LLM 모듈."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROMPT_VERSION = "place_address_v1"
AUTO_APPLY_LLM_CONFIDENCE = 0.75


class PlaceAddressInferencePayload(BaseModel):
    """LLM 구조화 응답."""

    model_config = ConfigDict(extra="forbid")

    address: str = Field(description="부산 내 도로명 또는 지번 주소")
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


@dataclass(frozen=True)
class PlaceAddressInference:
    """주소 추론 결과."""

    address: str
    confidence: float
    reason: str
    model_name: str
    prompt_version: str = PROMPT_VERSION


def build_place_address_prompt(
    *,
    name: str,
    source_region: str | None,
    tel: str | None,
    representative_menu: str | None,
    menu_names: tuple[str, ...],
) -> str:
    """LLM에 넘길 사용자 프롬프트."""
    menu_lines = "\n".join(f"- {menu}" for menu in menu_names[:8]) or "- (없음)"
    return (
        "다음은 부산광역시 착한가격업소 후보입니다. 실제 존재할 법한 부산 내 주소를 추론하세요.\n"
        "확실하지 않으면 confidence를 낮게 주세요. 다른 도시 주소는 금지입니다.\n\n"
        f"업소명: {name}\n"
        f"구군/동: {source_region or '(없음)'}\n"
        f"전화: {tel or '(없음)'}\n"
        f"대표메뉴: {representative_menu or '(없음)'}\n"
        f"메뉴:\n{menu_lines}\n\n"
        'JSON만 반환: {"address":"...", "confidence":0.0, "reason":"..."}'
    )


def parse_place_address_inference(
    raw_text: str,
    *,
    model_name: str,
) -> PlaceAddressInference | None:
    """LLM JSON 응답을 파싱."""
    try:
        payload = json.loads(raw_text)
        if not isinstance(payload, dict):
            return None
        parsed = PlaceAddressInferencePayload.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError):
        return None

    address = parsed.address.strip()
    if not address:
        return None

    return PlaceAddressInference(
        address=address,
        confidence=parsed.confidence,
        reason=parsed.reason.strip(),
        model_name=model_name,
    )


async def infer_place_address(
    *,
    api_key: str,
    model_name: str,
    name: str,
    source_region: str | None,
    tel: str | None,
    representative_menu: str | None,
    menu_names: tuple[str, ...],
) -> PlaceAddressInference | None:
    """OpenAI로 부산 내 주소 후보를 추론."""
    if not api_key:
        return None

    client = AsyncOpenAI(api_key=api_key)
    response = await client.chat.completions.create(
        model=model_name,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 한국 부산 음식점 주소 조사 보조입니다. "
                    "추측 주소를 JSON으로만 반환하고, 불확실하면 confidence를 낮게 설정합니다."
                ),
            },
            {
                "role": "user",
                "content": build_place_address_prompt(
                    name=name,
                    source_region=source_region,
                    tel=tel,
                    representative_menu=representative_menu,
                    menu_names=menu_names,
                ),
            },
        ],
    )
    content = response.choices[0].message.content
    if not content:
        return None
    return parse_place_address_inference(content, model_name=model_name)

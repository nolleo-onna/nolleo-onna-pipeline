"""SHA-256 해시 유틸리티.

[이 파일이 왜 있냐]
operation.md §3: SPOT_DETAILS.overview_hash, SPOT_EMBEDDINGS.source_hash는
원본 텍스트의 SHA-256(hex 64자)으로 생성. 같은 입력이면 같은 해시 → 비교만으로
"내용 바뀌었는지" 판정 가능 → LLM/임베딩 재호출 skip 가능.
"""

from __future__ import annotations

import hashlib


def sha256_hex(raw: str) -> str:
    """문자열의 SHA-256 hex 다이제스트(64자)를 반환.

    >>> sha256_hex("hello")
    '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'

    한국어든 영어든 utf-8로 인코딩 후 해싱하므로 동일 입력 → 동일 출력.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
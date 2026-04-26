"""동기화 실행 로그 컨텍스트."""

from dataclasses import dataclass


@dataclass(slots=True)
class SyncLogContext:
    """동기화 단위 로그 컨텍스트."""

    domain: str
    run_id: str
    source: str


def build_sync_log_context(domain: str, run_id: str, source: str) -> SyncLogContext:
    """SyncLogContext를 생성한다."""
    raise NotImplementedError
"""SYNC_LOGS helper placeholders."""


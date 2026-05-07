"""ADR 0003 — _refresh_cache_if_safe 가드 4종 단위 테스트.

DB 없이 _load_previous_sync_metadata와 repo를 mock으로 주입해 가드 분기와
예외 흡수만 검증한다. 실제 SQL 정확성은 별도 testcontainers 테스트(트랙 B).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from nolleo_pipeline.domains.congestion.pipeline import _refresh_cache_if_safe
from nolleo_pipeline.domains.congestion.repository import CongestionRepository

PIPELINE_MODULE = "nolleo_pipeline.domains.congestion.pipeline"


# ─── 헬퍼 ────────────────────────────────────────────────


def _make_ctx() -> Any:
    """SyncLogContext의 표면(.metadata)만 흉내."""
    return SimpleNamespace(
        metadata={
            "cache_skipped": None,
            "cache_skip_reason": None,
            "cache_updated_count": 0,
            "referenced_sync_log_id": None,
        }
    )


def _make_repo(
    *,
    refresh_return: int = 0,
    refresh_raises: Exception | None = None,
) -> CongestionRepository:
    """CongestionRepository 인터페이스의 AsyncMock."""
    repo = AsyncMock(spec=CongestionRepository)
    if refresh_raises is not None:
        repo.refresh_today_concentration_cache = AsyncMock(side_effect=refresh_raises)
    else:
        repo.refresh_today_concentration_cache = AsyncMock(return_value=refresh_return)
    return cast(CongestionRepository, repo)


def _patch_load(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sync_id: int = 42,
    bootstrap_complete: bool = True,
    stopped_by_budget: bool = False,
    null_content_id_count: int = 0,
    records_fetched: int = 1000,
    records_upserted: int = 1000,
    records_failed: int = 0,
    return_none: bool = False,
) -> None:
    """_load_previous_sync_metadata를 fake로 대체."""
    async def fake_load(_job_name: str) -> tuple[int, dict[str, Any], int, int, int] | None:
        if return_none:
            return None
        return (
            sync_id,
            {
                "bootstrap_complete": bootstrap_complete,
                "stopped_by_budget": stopped_by_budget,
                "null_content_id_count": null_content_id_count,
            },
            records_fetched,
            records_upserted,
            records_failed,
        )

    monkeypatch.setattr(f"{PIPELINE_MODULE}._load_previous_sync_metadata", fake_load)


async def _call(repo: CongestionRepository, ctx: Any) -> None:
    await _refresh_cache_if_safe(
        repo=repo,
        ctx=ctx,
        max_failure_rate=0.05,
        max_null_ratio=0.3,
    )


# ─── no_previous_sync (콜드 스타트) ──────────────────────


@pytest.mark.asyncio
async def test_skipped_when_no_previous_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """직전 success 회차가 없으면 cache_skip_reason='no_previous_sync'."""
    _patch_load(monkeypatch, return_none=True)
    ctx = _make_ctx()
    repo = _make_repo()

    await _call(repo, ctx)

    assert ctx.metadata["cache_skipped"] is True
    assert ctx.metadata["cache_skip_reason"] == "no_previous_sync"
    cast(AsyncMock, repo.refresh_today_concentration_cache).assert_not_called()


# ─── 가드 1: partial_sync ─────────────────────────────────


@pytest.mark.asyncio
async def test_skipped_when_bootstrap_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    """가드 1: bootstrap_complete=False → 'partial_sync'."""
    _patch_load(monkeypatch, bootstrap_complete=False)
    ctx = _make_ctx()
    repo = _make_repo()

    await _call(repo, ctx)

    assert ctx.metadata["cache_skipped"] is True
    assert ctx.metadata["cache_skip_reason"] == "partial_sync"
    cast(AsyncMock, repo.refresh_today_concentration_cache).assert_not_called()


# ─── 가드 2: stopped_by_budget ────────────────────────────


@pytest.mark.asyncio
async def test_skipped_when_stopped_by_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """가드 2: stopped_by_budget=True → 'stopped_by_budget'."""
    _patch_load(monkeypatch, stopped_by_budget=True)
    ctx = _make_ctx()
    repo = _make_repo()

    await _call(repo, ctx)

    assert ctx.metadata["cache_skipped"] is True
    assert ctx.metadata["cache_skip_reason"] == "stopped_by_budget"
    cast(AsyncMock, repo.refresh_today_concentration_cache).assert_not_called()


# ─── 가드 3: high_failure_rate ────────────────────────────


@pytest.mark.asyncio
async def test_skipped_when_failure_rate_high(monkeypatch: pytest.MonkeyPatch) -> None:
    """가드 3: failure_rate ≥ max_failure_rate → 'high_failure_rate'."""
    _patch_load(
        monkeypatch,
        records_fetched=100,
        records_failed=10,                                        # 10% > 5%
        records_upserted=90,
    )
    ctx = _make_ctx()
    repo = _make_repo()

    await _call(repo, ctx)

    assert ctx.metadata["cache_skipped"] is True
    assert ctx.metadata["cache_skip_reason"] == "high_failure_rate"
    cast(AsyncMock, repo.refresh_today_concentration_cache).assert_not_called()


# ─── 가드 4: high_null_ratio ──────────────────────────────


@pytest.mark.asyncio
async def test_skipped_when_null_ratio_high(monkeypatch: pytest.MonkeyPatch) -> None:
    """가드 4: null_ratio ≥ max_null_ratio → 'high_null_ratio'."""
    _patch_load(
        monkeypatch,
        records_upserted=1000,
        null_content_id_count=400,                                # 40% > 30%
    )
    ctx = _make_ctx()
    repo = _make_repo()

    await _call(repo, ctx)

    assert ctx.metadata["cache_skipped"] is True
    assert ctx.metadata["cache_skip_reason"] == "high_null_ratio"
    cast(AsyncMock, repo.refresh_today_concentration_cache).assert_not_called()


# ─── 모든 가드 통과 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_refreshed_when_all_guards_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """모든 가드 통과 → repo.refresh 호출, metadata에 결과 기록."""
    _patch_load(monkeypatch, records_upserted=1000, null_content_id_count=100)  # null_ratio=10%
    ctx = _make_ctx()
    repo = _make_repo(refresh_return=850)

    await _call(repo, ctx)

    assert ctx.metadata["cache_skipped"] is False
    assert ctx.metadata["cache_skip_reason"] is None
    assert ctx.metadata["cache_updated_count"] == 850
    assert ctx.metadata["referenced_sync_log_id"] == 42
    cast(AsyncMock, repo.refresh_today_concentration_cache).assert_called_once()


# ─── 예외 흡수 (ADR 0003 §4) ──────────────────────────────


@pytest.mark.asyncio
async def test_exception_during_refresh_is_absorbed(monkeypatch: pytest.MonkeyPatch) -> None:
    """가드 통과 후 SQL 실패는 try/except로 흡수, sync 잡 'failed' 안 만듦.

    ADR 0003 §4 — 캐시 갱신 실패가 핵심 적재 success를 가리지 않음.
    """
    _patch_load(monkeypatch, records_upserted=1000, null_content_id_count=100)
    ctx = _make_ctx()
    repo = _make_repo(refresh_raises=RuntimeError("connection lost"))

    # raise 안 하고 정상 종료해야 함
    await _call(repo, ctx)

    assert ctx.metadata["cache_skipped"] is True
    assert ctx.metadata["cache_skip_reason"] == "exception"
    errors = ctx.metadata.get("errors", [])
    assert any(
        err.get("stage") == "cache_refresh" and "connection lost" in err.get("error", "")
        for err in errors
    )

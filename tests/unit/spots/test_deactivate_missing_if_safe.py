"""ADR 0003 — _deactivate_missing_if_safe 가드 4종 단위 테스트.

DB 없이 ctx/repo를 mock으로 주입해 가드 분기와 예외 흡수만 검증한다.
SQL 자체 정확성은 별도 testcontainers 테스트(트랙 B)에서 본다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from nolleo_pipeline.domains.spots.pipeline import _deactivate_missing_if_safe
from nolleo_pipeline.domains.spots.repository import SpotsRepository


def _make_ctx(
    *,
    bootstrap_complete: bool = True,
    stopped_by_budget: bool = False,
    records_fetched: int = 100,
    records_failed: int = 0,
) -> Any:
    """SyncLogContext 인터페이스를 흉내낸 SimpleNamespace.

    헬퍼가 실제로 만지는 표면(.metadata, .records_fetched, .records_failed)만 흉내낸다.
    """
    return SimpleNamespace(
        metadata={
            "bootstrap_complete": bootstrap_complete,
            "stopped_by_budget": stopped_by_budget,
            "deactivated_count": 0,
            "deactivation_skipped": None,
            "deactivation_skip_reason": None,
            "deactivation_failure_rate": None,
            "deactivation_ratio": None,
        },
        records_fetched=records_fetched,
        records_failed=records_failed,
    )


def _make_repo(
    *,
    active: int = 1000,
    candidates: int = 50,
    deactivated: list[str] | None = None,
    raise_on_deactivate: Exception | None = None,
) -> SpotsRepository:
    """SpotsRepository 인터페이스의 AsyncMock."""
    repo = AsyncMock(spec=SpotsRepository)
    repo.count_active = AsyncMock(return_value=active)
    repo.count_deactivation_candidates = AsyncMock(return_value=candidates)
    if raise_on_deactivate is not None:
        repo.deactivate_missing = AsyncMock(side_effect=raise_on_deactivate)
    else:
        repo.deactivate_missing = AsyncMock(return_value=deactivated or [])
    return cast(SpotsRepository, repo)


async def _call(repo: SpotsRepository, ctx: Any) -> None:
    await _deactivate_missing_if_safe(
        repo=repo,
        ctx=ctx,
        regions=["26"],
        content_type_ids=["12", "14", "39"],
        sync_started_at=datetime(2026, 5, 7, 0, 0, tzinfo=UTC),
        max_failure_rate=0.05,
        max_deactivation_ratio=0.2,
    )


@pytest.mark.asyncio
async def test_skipped_when_bootstrap_incomplete() -> None:
    """가드 1: bootstrap_complete=False면 비활성 실행 안 함."""
    ctx = _make_ctx(bootstrap_complete=False)
    repo = _make_repo()

    await _call(repo, ctx)

    assert ctx.metadata["deactivation_skipped"] is True
    assert ctx.metadata["deactivation_skip_reason"] == "partial_sync"
    cast(AsyncMock, repo.deactivate_missing).assert_not_called()


@pytest.mark.asyncio
async def test_skipped_when_stopped_by_budget() -> None:
    """가드 2: 예산 컷으로 중단된 회차는 비활성 미실행."""
    ctx = _make_ctx(stopped_by_budget=True)
    repo = _make_repo()

    await _call(repo, ctx)

    assert ctx.metadata["deactivation_skipped"] is True
    assert ctx.metadata["deactivation_skip_reason"] == "stopped_by_budget"
    cast(AsyncMock, repo.deactivate_missing).assert_not_called()


@pytest.mark.asyncio
async def test_skipped_when_failure_rate_exceeds_threshold() -> None:
    """가드 3: 에러율이 임계값 이상이면 비활성 미실행."""
    ctx = _make_ctx(records_fetched=100, records_failed=10)  # 10% > 5%
    repo = _make_repo()

    await _call(repo, ctx)

    assert ctx.metadata["deactivation_skipped"] is True
    assert ctx.metadata["deactivation_skip_reason"] == "high_failure_rate"
    assert ctx.metadata["deactivation_failure_rate"] == pytest.approx(0.1)
    cast(AsyncMock, repo.deactivate_missing).assert_not_called()


@pytest.mark.asyncio
async def test_skipped_when_deactivation_ratio_exceeds_threshold() -> None:
    """가드 4: 비활성 비율이 임계 이상이면 dry-run만 하고 skip."""
    ctx = _make_ctx()
    repo = _make_repo(active=1000, candidates=300)  # 30% > 20%

    await _call(repo, ctx)

    assert ctx.metadata["deactivation_skipped"] is True
    assert ctx.metadata["deactivation_skip_reason"] == "high_deactivation_ratio"
    assert ctx.metadata["deactivation_ratio"] == pytest.approx(0.3)
    cast(AsyncMock, repo.deactivate_missing).assert_not_called()


@pytest.mark.asyncio
async def test_ratio_zero_when_no_active_rows() -> None:
    """가드 4: 활성 row가 0이면 ZeroDivisionError 없이 ratio=0.0으로 통과."""
    ctx = _make_ctx()
    repo = _make_repo(active=0, candidates=0)

    await _call(repo, ctx)

    assert ctx.metadata["deactivation_ratio"] == 0.0
    assert ctx.metadata["deactivation_skipped"] is False
    cast(AsyncMock, repo.deactivate_missing).assert_called_once()


@pytest.mark.asyncio
async def test_deactivates_when_all_guards_pass() -> None:
    """모든 가드 통과 시 deactivate_missing 호출 + metadata 기록."""
    ctx = _make_ctx()
    repo = _make_repo(active=1000, candidates=50, deactivated=["c1", "c2", "c3"])

    await _call(repo, ctx)

    assert ctx.metadata["deactivation_skipped"] is False
    assert ctx.metadata["deactivation_skip_reason"] is None
    assert ctx.metadata["deactivated_count"] == 3
    assert ctx.metadata["deactivation_ratio"] == pytest.approx(0.05)
    cast(AsyncMock, repo.deactivate_missing).assert_called_once()


@pytest.mark.asyncio
async def test_exception_during_deactivate_is_absorbed() -> None:
    """가드 통과 후 SQL 실패는 try/except로 흡수, sync 잡 'failed' 안 만듦."""
    ctx = _make_ctx()
    repo = _make_repo(
        active=1000,
        candidates=50,
        raise_on_deactivate=RuntimeError("connection lost"),
    )

    await _call(repo, ctx)

    assert ctx.metadata["deactivation_skipped"] is True
    assert ctx.metadata["deactivation_skip_reason"] == "exception"
    errors = ctx.metadata.get("errors", [])
    assert any(
        err.get("stage") == "deactivation" and "connection lost" in err.get("error", "")
        for err in errors
    )

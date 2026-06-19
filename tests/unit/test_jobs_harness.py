"""Job 레지스트리 + run_job 래퍼 단위 테스트."""

from __future__ import annotations

import pytest

from nolleo_pipeline.common import jobs as jobs_mod
from nolleo_pipeline.common.jobs import JobSpec, all_jobs, get_job, register, run_job


@pytest.fixture(autouse=True)
def _isolate_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """각 테스트가 깨끗한 레지스트리에서 시작하도록 격리."""
    monkeypatch.setattr(jobs_mod, "_REGISTRY", {})


def test_register_and_get() -> None:
    async def fake() -> None: ...

    spec = JobSpec(name="job_a", fn=fake, description="설명")
    register(spec)
    assert get_job("job_a") is spec
    assert [j.name for j in all_jobs()] == ["job_a"]


def test_duplicate_name_rejected() -> None:
    async def fake() -> None: ...

    register(JobSpec(name="dup", fn=fake))
    with pytest.raises(ValueError, match="중복"):
        register(JobSpec(name="dup", fn=fake))


def test_unknown_job_lists_candidates() -> None:
    async def fake() -> None: ...

    register(JobSpec(name="known", fn=fake))
    with pytest.raises(KeyError, match="known"):
        get_job("nope")


@pytest.mark.asyncio
async def test_run_job_forwards_accepted_params(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, object] = {}

    async def fake(*, max_pages: int | None = None) -> None:
        received["max_pages"] = max_pages

    register(JobSpec(name="j", fn=fake))
    monkeypatch.setattr(jobs_mod, "close_pool", _noop)

    await run_job("j", params={"max_pages": 3})
    assert received == {"max_pages": 3}


@pytest.mark.asyncio
async def test_run_job_rejects_unknown_param(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(*, max_pages: int | None = None) -> None: ...

    register(JobSpec(name="j", fn=fake))
    monkeypatch.setattr(jobs_mod, "close_pool", _noop)

    with pytest.raises(ValueError, match="받지 않는 파라미터"):
        await run_job("j", params={"bogus": 1})


@pytest.mark.asyncio
async def test_run_job_injects_run_type_only_when_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    async def accepts(*, run_type: str = "manual") -> None:
        seen["run_type"] = run_type

    async def ignores() -> None:
        seen["called"] = True

    register(JobSpec(name="a", fn=accepts, default_run_type="manual"))
    register(JobSpec(name="b", fn=ignores))
    monkeypatch.setattr(jobs_mod, "close_pool", _noop)

    await run_job("a", run_type="scheduled")
    await run_job("b", run_type="scheduled")  # run_type 인자 없어도 깨지지 않음
    assert seen == {"run_type": "scheduled", "called": True}


@pytest.mark.asyncio
async def test_run_job_closes_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    closed = {"n": 0}

    async def fake() -> None: ...

    async def fake_close() -> None:
        closed["n"] += 1

    register(JobSpec(name="j", fn=fake))
    monkeypatch.setattr(jobs_mod, "close_pool", fake_close)

    await run_job("j")
    assert closed["n"] == 1


async def _noop() -> None:
    return None

"""Job 레지스트리 + 통합 러너.

[이 파일이 왜 있냐]
- 지금까지 scripts/run_*.py 십수 개가 각자 `asyncio.run → 파이프라인 호출 → close_pool`을
  복붙해 왔다. 잡을 "한 곳에 등록"하고 "한 가지 방법으로 실행"하게 만드는 게 목표.
- CLI(`nolleo run <job>`), 스케줄러, 테스트가 모두 이 레지스트리/`run_job`을 통해
  동일하게 잡을 실행한다 → 수동 실행과 cron 실행이 코드상 같아진다.

[레지스트리 name 규약]
- JobSpec.name 은 sync_logs.job_name 과 동일하게 맞춘다 (단일 식별자).
  예: "tourapi_courses_sync" → sync_log_run("tourapi_courses_sync") 와 일치.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from nolleo_pipeline.common.db import close_pool

# 잡 진입점 시그니처: keyword-only 파라미터를 받아 1회 실행하고 None 반환.
JobFn = Callable[..., Awaitable[object]]


@dataclass(frozen=True)
class JobSpec:
    """등록 가능한 단일 잡의 메타데이터.

    Attributes:
        name: sync_logs.job_name 과 일치하는 잡 식별자.
        fn: 기존 run_*_sync 진입점. keyword-only 인자를 받는다.
        description: `nolleo list` 에 표시되는 한 줄 설명.
        default_run_type: 명시 안 했을 때 sync_logs.run_type 기본값.
    """

    name: str
    fn: JobFn
    description: str = ""
    default_run_type: str = "manual"


_REGISTRY: dict[str, JobSpec] = {}


def register(spec: JobSpec) -> JobSpec:
    """잡을 전역 레지스트리에 등록한다. 중복 name 은 오류."""
    if spec.name in _REGISTRY:
        raise ValueError(f"중복된 job name: {spec.name!r}")
    _REGISTRY[spec.name] = spec
    return spec


def get_job(name: str) -> JobSpec:
    """이름으로 잡을 조회한다. 없으면 후보를 보여주며 오류."""
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "(등록된 잡 없음)"
        raise KeyError(f"알 수 없는 job: {name!r}. 등록된 잡: {known}") from None


def all_jobs() -> list[JobSpec]:
    """등록된 모든 잡을 name 순으로 반환한다."""
    return [_REGISTRY[name] for name in sorted(_REGISTRY)]


def _filter_params(spec: JobSpec, params: dict[str, object]) -> dict[str, object]:
    """잡 시그니처가 받는 인자만 남긴다. 받지 못하는 인자는 명확히 오류.

    CLI에서 `--max-pages` 같은 오타/미지원 파라미터를 조용히 흘려보내지 않고
    바로 알려주기 위함.
    """
    sig = inspect.signature(spec.fn)
    accepted = set(sig.parameters)
    unknown = [key for key in params if key not in accepted]
    if unknown:
        raise ValueError(
            f"job {spec.name!r} 가 받지 않는 파라미터: {', '.join(unknown)}. "
            f"허용: {', '.join(sorted(accepted)) or '(없음)'}"
        )
    return params


async def run_job(
    name: str,
    *,
    run_type: str | None = None,
    params: dict[str, object] | None = None,
    close: bool = True,
) -> object:
    """잡 1회 실행 — 모든 진입점(CLI/스케줄러/수동)의 공통 래퍼.

    지금까지 scripts/ 가 복붙하던 try/finally close_pool 보일러플레이트를 여기서 흡수한다.
    sync_logs 기록은 여전히 각 도메인의 run_*_sync 내부 sync_log_run 이 담당한다
    (레지스트리-우선 단계에서는 도메인 흐름을 건드리지 않는다).

    Args:
        name: 등록된 잡 이름.
        run_type: sync_logs.run_type. 잡 fn이 run_type 인자를 받을 때만 전달된다.
                  None이면 잡의 default_run_type 사용.
        params: 잡 fn에 넘길 keyword 인자.
        close: 종료 시 커넥션 풀을 닫을지. 한 프로세스에서 여러 잡을 연속 실행하는
               스케줄러에서는 False로 두고 마지막에 한 번만 닫는다.
    """
    spec = get_job(name)
    call_params = dict(params or {})

    effective_run_type = run_type if run_type is not None else spec.default_run_type
    if "run_type" in inspect.signature(spec.fn).parameters:
        call_params.setdefault("run_type", effective_run_type)

    call_params = _filter_params(spec, call_params)

    try:
        return await spec.fn(**call_params)
    finally:
        if close:
            await close_pool()

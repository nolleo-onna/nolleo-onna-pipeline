"""nolleo 파이프라인 CLI — 잡 실행 단일 진입점.

[이 파일이 왜 있냐]
- scripts/run_*.py 십수 개를 대체한다. `uv run nolleo run <job>` 한 줄로 실행.
- 카탈로그(jobs.catalog)를 import 해 등록된 잡을 노출한다.

[설계 — 시그니처에서 플래그 자동 도출]
- 각 잡의 run_*_sync 시그니처를 introspection 해서 `--flag`를 자동 생성한다.
  잡을 카탈로그에 등록하기만 하면 CLI 플래그가 따라온다 (수동 유지보수 0).
- 타입 매핑: bool→store_true, int/float/str/Path→해당 타입, 그 외(tuple 등)는
  노출하지 않고 잡의 기본값을 사용.

사용법:
    uv run nolleo list
    uv run nolleo run tourapi_courses_sync --max-pages 2
    uv run nolleo run food_spot_rule_match --dry-run --limit 100
    uv run nolleo run <job> --help        # 잡별 플래그 확인
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import sys
import types
import typing
from pathlib import Path

import nolleo_pipeline.jobs.catalog  # noqa: F401  (import 시 잡 등록)
from nolleo_pipeline.common.jobs import JobSpec, all_jobs, get_job, run_job

# 시그니처에서 노출하지 않는 파라미터 (특수 처리하거나 의미 없음).
_SKIP_PARAMS = {"run_type"}


def _non_none_types(hint: object) -> list[object]:
    """`int | None` → [int] 처럼 Optional 을 벗긴 실제 타입 목록."""
    origin = typing.get_origin(hint)
    if origin in (typing.Union, types.UnionType):
        return [arg for arg in typing.get_args(hint) if arg is not type(None)]
    return [hint]


def _param_flag(name: str) -> str:
    """파라미터명 → kebab-case 플래그. l_dong_regn_cd → --l-dong-regn-cd."""
    return "--" + name.replace("_", "-")


def _add_param_arg(
    parser: argparse.ArgumentParser,
    name: str,
    param: inspect.Parameter,
    hint: object,
) -> bool:
    """파라미터 하나를 argparse 인자로 추가. 노출 못 하면 False 반환.

    required(기본값 없음) 인 파라미터를 노출 못 하면 ValueError.
    """
    required = param.default is inspect.Parameter.empty
    candidates = _non_none_types(hint)

    flag = _param_flag(name)
    if bool in candidates:
        # bool 기본값은 모두 False 전제 → store_true. 미지정 시 잡 기본값 사용.
        parser.add_argument(flag, action="store_true", default=None, help="(flag)")
        return True
    for py_type in (int, float, str, Path):
        if py_type in candidates:
            arg_type = str if py_type is Path else py_type
            parser.add_argument(flag, type=arg_type, default=None, required=required)
            return True

    if required:
        raise ValueError(
            f"파라미터 {name!r}(타입 {hint!r})는 CLI로 노출할 수 없는데 필수입니다. "
            f"해당 잡은 CLI 대신 코드에서 직접 호출하세요."
        )
    return False  # 노출 불가하지만 기본값이 있으므로 그냥 스킵


def _build_run_parser(job: JobSpec) -> argparse.ArgumentParser:
    """잡 시그니처로부터 `nolleo run <job>` 전용 파서를 만든다."""
    parser = argparse.ArgumentParser(
        prog=f"nolleo run {job.name}",
        description=job.description,
    )
    parser.add_argument(
        "--run-type",
        default=None,
        help="sync_logs.run_type (manual|scheduled|triggered|regression). 기본: 잡 정의값",
    )
    hints = typing.get_type_hints(job.fn)
    sig = inspect.signature(job.fn)
    for name, param in sig.parameters.items():
        if name in _SKIP_PARAMS or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        _add_param_arg(parser, name, param, hints.get(name, str))
    return parser


def _collect_params(job: JobSpec, parsed: argparse.Namespace) -> dict[str, object]:
    """파싱 결과에서 명시적으로 넘긴 값만 params 로 추린다 (None=미지정)."""
    sig = inspect.signature(job.fn)
    params: dict[str, object] = {}
    for name in sig.parameters:
        if name in _SKIP_PARAMS:
            continue
        value = getattr(parsed, name, None)
        if value is not None:
            params[name] = value
    return params


def _cmd_list() -> int:
    jobs = all_jobs()
    if not jobs:
        print("등록된 잡이 없습니다.")
        return 0
    width = max(len(job.name) for job in jobs)
    for job in jobs:
        print(f"  {job.name:<{width}}  {job.description}")
    return 0


def _cmd_run(rest: list[str]) -> int:
    # 1단계: 잡 이름과 --run-type 만 먼저 뽑는다.
    pre = argparse.ArgumentParser(prog="nolleo run", add_help=False)
    pre.add_argument("job")
    pre.add_argument("--run-type", default=None)
    known, remaining = pre.parse_known_args(rest)

    job = get_job(known.job)  # 미존재 시 KeyError → main 에서 처리

    # 2단계: 잡별 플래그를 시그니처로 만들어 나머지를 파싱 (--help 도 여기서 동작).
    parser = _build_run_parser(job)
    parsed = parser.parse_args(remaining)
    run_type = known.run_type if known.run_type is not None else parsed.run_type

    params = _collect_params(job, parsed)
    result = asyncio.run(run_job(job.name, run_type=run_type, params=params))
    if result is not None:
        print(f"결과: {result}")
    print(f"완료: {job.name}")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("사용법: nolleo <list|run> ...\n  nolleo list\n  nolleo run <job> [--flags]")
        return 0
    command, rest = argv[0], argv[1:]
    try:
        if command == "list":
            return _cmd_list()
        if command == "run":
            if not rest:
                print("오류: 실행할 잡 이름이 필요합니다. `nolleo list` 로 확인하세요.")
                return 2
            return _cmd_run(rest)
    except (KeyError, ValueError) as exc:
        # 잡 미존재/파라미터 오류 등 사용자 입력 오류 → 트레이스백 없이 종료코드 2.
        print(f"오류: {exc}")
        return 2
    print(f"오류: 알 수 없는 명령 {command!r}. list 또는 run 을 쓰세요.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

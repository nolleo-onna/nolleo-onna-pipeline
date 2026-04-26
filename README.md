# 놀러온나 파이프라인

부산 청년 여행자를 위한 하루 코스 의사결정 서비스 **놀러온나**의 데이터 파이프라인 레포입니다.

## 프로젝트 개요

- TourAPI 4.0 데이터를 수집해 RDS PostgreSQL에 사전 적재
- LLM 태그/요약 + OpenAI 임베딩(pgvector)을 생성해 검색/추천 품질 강화
- 운영 방식: 초기 1회 벌크 + 매일 새벽 증분 갱신
- 사용자 요청 경로에서 TourAPI를 직접 호출하지 않도록 설계

## 레포 책임 범위

이 레포가 하는 일:

1. TourAPI(부산) 수집
2. 태그/요약 생성
3. 임베딩 생성
4. DB upsert
5. 증분 갱신 파이프라인 실행

이 레포가 하지 않는 일:

- REST API 서빙 (Spring Boot 레포)
- 프론트엔드
- 실시간 사용자 요청 처리

## 외부 API

- TourAPI Base URL: `http://apis.data.go.kr/B551011/KorService2`
- OpenAI 모델:
  - 태그/요약: `gpt-4o-mini`
  - 임베딩: `text-embedding-3-small` (1536)

## 기술 스택

- Python 3.11+
- SQLAlchemy 2.0 (sync session)
- PostgreSQL 16 + pgvector
- httpx, tenacity, pydantic v2, python-dotenv, loguru, openai

## 구조

```text
nolleo-onna-pipeline/
├── .env.example
├── .gitignore
├── README.md
├── pyproject.toml
├── schema.sql
├── src/
│   ├── config.py
│   ├── constants.py
│   ├── db/
│   ├── clients/
│   ├── schemas/
│   ├── pipelines/
│   └── utils/
├── scripts/
│   ├── check_db.py
│   └── run_bulk_sync.py
└── tests/
```

## 구현 규칙 요약

- SQL write는 upsert 패턴 기반으로 구현
- 환경변수는 `src/config.py`에서만 로드
- 로깅은 loguru 통일
- TourAPI는 3회 재시도(5xx/timeout 한정)
- API 콜 한도 추적(rate limiter) 적용 예정
- `detailIntro2` 타입별 필드는 공통 파서로 정규화
- 여행코스(25)는 코스/하위 스팟 2단 저장
- 증분은 `areaBasedSyncList2` 기반 갱신

## 환경변수

```bash
cp .env.example .env
```
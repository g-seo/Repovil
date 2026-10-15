# AI OSS Momentum Tracker — MVP 구현 계획

## 1. 문서 목적과 원칙

이 문서는 `docs/PRD.md`의 MVP를 의존성 순서대로 구현하고 진행 상태를 추적하기 위한 계획이다. 제품 동작의 Source of Truth는 항상 PRD이며, 이 문서는 PRD를 보완하거나 변경하지 않는다.

- PRD와 이 문서가 충돌하면 PRD를 따른다.
- 구현 전에 해당 Phase와 관련된 PRD 절을 다시 확인한다.
- 한 번에 한 Phase만 구현하고, 완료 조건과 테스트를 모두 통과한 뒤 다음 Phase로 이동한다.
- 제품 동작에 영향을 주는 모호함이나 GitHub API의 실제 동작과 PRD의 충돌은 임의로 결정하지 않고 사용자에게 확인한다.
- MVP 밖의 기능과 미래 확장을 위한 추상화는 구현하지 않는다.
- GitHub 호출은 background worker의 `GitHubClient`를 통해서만 수행하고, 사용자 요청 경로는 PostgreSQL만 읽는다.
- PostgreSQL의 snapshot과 bootstrap 원천 데이터는 보존한다. stale snapshot을 최신값처럼 사용하지 않는다.
- 모든 애플리케이션 timestamp는 UTC로 저장하고 반환한다.

### 상태 표기

- `[ ]`: 시작 전
- `[~]`: 진행 중
- `[x]`: 완료
- `[!]`: 차단됨 — 원인과 필요한 결정을 항목 아래 기록

각 Phase 완료 시 구현 항목, 완료 조건, 테스트 항목을 갱신하고 실행한 명령과 결과를 해당 Phase의 `실행 기록`에 남긴다. 테스트를 실행하지 않았다면 완료로 표시하지 않는다.

### 의존성 순서

`Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15 → 16`

## 2. MVP 범위

### 포함

- 설정된 GitHub Topic을 이용한 일일 discovery
- public, non-fork, non-archived, stars 200 이상 repository의 저장·비활성화·재활성화
- 6시간 간격 snapshot 수집 및 모든 과거 snapshot 보존
- 신규 repository의 7d/30d historical bootstrap과 추정 여부 표시
- 24h/7d/30d growth ranking, 카테고리 필터, 20개 단위 페이지네이션
- 95% 성공률을 기준으로 한 tracking run 단위 원자적 랭킹 공개
- repository 상세와 최근 30일 star history
- FastAPI 읽기 전용 API, Next.js 웹 UI, PostgreSQL, Alembic
- Railway 배포 및 Railway Cron 기반 discovery/tracking 실행

### 제외

- 로그인, watchlist, 알림, 비교, 추천
- LLM 분석 또는 분류, 관리자 UI
- GraphQL tracking 전환, webhook, 과거 snapshot downsampling
- Redis, Celery, Kafka, Kubernetes
- PRD에 없는 운영 대시보드나 범용 프레임워크

## 3. 공통 품질 게이트

모든 구현 Phase에 다음 기준을 적용한다.

- [ ] 새 business logic에 정상·경계·실패 테스트를 추가한다.
- [ ] 외부 GitHub 호출은 fixture/mock으로 재현 가능하게 테스트하고 live API 테스트는 별도로 표시한다.
- [ ] 관련 backend test, lint, type check를 실행한다.
- [ ] 관련 frontend test, lint, type check를 실행한다.
- [ ] DB 변경은 Alembic migration으로만 수행하고 새 DB upgrade와 downgrade/upgrade 경로를 검증한다.
- [ ] 사용자 변경과 현재 Phase 밖의 파일을 수정하지 않는다.
- [ ] 문서·로그·fixture에 token이나 secret을 남기지 않는다.

기본 검증 명령은 Phase 2에서 확정한다. 목표 명령은 다음과 같다.

```text
uv run pytest
uv run ruff check .
uv run mypy <backend-package>
npm run test
npm run lint
npm run typecheck
npm run build
```

## 4. Phase별 계획

## Phase 0 — PRD 계약 고정과 결정 게이트

**목표:** 구현 전에 MVP 경계, 용어, 공개 규칙을 테스트 가능한 계약으로 정리한다.

**선행 조건:** 없음

**상태:** `[x]` — 2026-10-10 완료

### 구현 항목

- [x] PRD의 discovery 자격, 비활성화/재활성화, bootstrap, baseline, ranking, publication 규칙을 acceptance checklist로 옮긴다.
- [x] `success`, `failed`, `skipped`의 판정표를 PRD 문구에 맞춰 작성한다. transient API 오류와 자격 상실을 구분한다.
- [x] API 응답 계약에서 `데이터 준비 중`, 빈 결과, not found를 구분할 최소 schema를 정리한다.
- [x] 상세 그래프에서 실제 snapshot과 bootstrap 추정치가 겹칠 때 실제 snapshot을 우선한다는 PRD 원칙을 테스트 사례로 명시한다.
- [x] 다음 항목이 PRD만으로 결정되지 않으면 구현 전에 사용자 결정을 받는다.
  - tracking 도중 처음 확인된 deleted/private 상태를 `skipped`와 `failed` 중 무엇으로 집계할지
  - repository 상세/history endpoint의 정확한 not-found 응답 형식
  - category 설정에서 제거된 topic/category를 DB에서 비활성화할지 유지할지에 대한 sync 정책

### 완료 조건

- [x] 모든 MVP 완료 기준이 하나 이상의 Phase 및 테스트 항목에 연결된다.
- [x] 미결정 제품 동작이 숨겨진 구현 가정으로 남아 있지 않다.
- [x] MVP 제외 기능이 어떤 Phase에도 포함되지 않는다.

### 테스트 방법

- [x] PRD 1~10절과 이 계획을 수동 대조한다.
- [x] 위 결정 게이트와 후속 Phase의 테스트 항목 사이에 누락이 없는지 review한다.

### 실행 기록

- 2026-10-10: `docs/MVP_ACCEPTANCE_CRITERIA.md` 작성. PRD 1~10절의 discovery, bootstrap, tracking, ranking, publication, API/UI, 운영 계약을 ID 기반 checklist와 필수 경계·실패 테스트로 연결.
- 2026-10-10: PRD와 구현 계획을 수동 대조하고 여섯 MVP 완료 기준이 후속 Phase 및 테스트에 모두 연결됨을 확인.
- 2026-10-10: 사용자 승인으로 DEC-01~03을 권장안대로 확정. tracking 중 확인된 deleted/private는 `skipped`, 상세/history not-found는 동일한 HTTP 404 계약, YAML 제거 항목은 history를 보존하는 soft-deactivate/re-activate 정책을 적용.
- 2026-10-10: Phase 0 완료. 요청에 따라 Phase 1은 시작하지 않음.

## Phase 1 — GitHub API 실현 가능성 검증

**목표:** production code 작성 전에 GitHub REST API의 실제 endpoint, 권한, 응답, pagination, rate limit이 PRD를 지원하는지 검증한다.

**선행 조건:** Phase 0

**상태:** `[x]` — 2026-10-10 인증/비인증 live 검증 완료

### 구현 항목

- [x] 검증 일자, 사용한 REST API version, 인증 방식, test repository/topic, 요청/응답 요약을 `docs/GITHUB_API_VALIDATION.md`에 기록한다. token과 개인 정보는 기록하지 않는다.
- [x] `GET /search/repositories`가 `topic`, `stars`, public/non-fork/non-archived 조건과 정렬·pagination을 실제로 지원하는지 확인한다.
- [x] Search가 반환하는 `total_count`, `incomplete_results`, 최대 1,000개 접근 제한, `per_page`/page 한계를 확인한다.
- [x] star 범위의 양 끝이 포함되는지 확인하고, 인접 구간 중복 방지 규칙을 정한다.
- [x] 결과가 1,000개를 넘는 구간을 재귀 분할할 수 있는지 표본 topic으로 검증한다. 단일 star 값 구간도 1,000개를 넘으면 해당 구간을 실패로 기록해야 하며, PRD 승인 없이 다른 발견 방식을 추가하지 않는다.
- [x] repository 조회에서 `github_id`, owner/name, topics, visibility, fork, archived, current star 수를 얻을 수 있는지와 rename redirect, 404 동작을 확인한다.
- [x] `GET /repos/{owner}/{repo}/stargazers/count`와 `GET /repos/{owner}/{repo}/stargazers/history`의 가용성, public repository 권한, 응답 형식, pagination을 live 요청으로 확인한다.
- [x] star history의 주별 묶음, 일별 `stars_created`, 최신순 page, UTC와 일치하지 않을 수 있는 경계, 최대 `per_page=30`/`page=100` 제약을 확인한다.
- [x] star history가 생성된 star 수이며 unstar를 복원하지 못한다는 점을 fixture 기대값에 반영한다.
- [x] 인증/비인증 primary rate limit, Search 전용 limit, `x-ratelimit-*`, `Retry-After`, 403/429 및 secondary limit 처리 규칙을 확인한다.
- [x] 예상 repository 수를 표본 검색으로 산정하고 daily discovery, 신규 bootstrap, 6시간 tracking의 요청 예산이 운영 가능한지 계산한다.
- [x] PRD의 `GitHubClient` 메서드 각각을 검증된 REST endpoint에 매핑한다. REST로 구현하며 GraphQL 전환은 MVP에서 제외한다.

### 완료 조건

- [x] Search 분할, metadata/status 조회, current star count, 30일 bootstrap에 필요한 데이터를 실제 API로 획득한 증거가 문서화된다.
- [x] endpoint별 권한·pagination·rate limit·실패 의미와 API version pinning 정책이 확정된다.
- [x] 요청 예산이 daily/6-hour schedule 안에서 가능한지 수치로 판단된다.
- [x] 실제 API가 PRD를 지원함을 확인했다. scraping이나 비공식 API를 도입하지 않는다.

### 테스트 방법

- [x] 인증된 read-only token으로 소형·중형·대형 public repository에 read-only smoke request를 실행한다.
- [x] 1,000건 이하/초과 search query, 마지막 page, `incomplete_results`를 검증한다.
- [x] rate-limit response header와 404/422/403 또는 429 fixture를 보존 가능한 형태로 정리한다.
- [x] GitHub 공식 문서와 live 결과의 차이를 기록한다.

### 공식 문서 기준선

- [Repository Search REST API](https://docs.github.com/en/rest/search/search)
- [Starring REST API](https://docs.github.com/en/rest/activity/starring)
- [REST API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)

### 실행 기록

- 2026-10-10: `docs/GITHUB_API_VALIDATION.md` 작성. GitHub REST API `2026-03-10`을 기준으로 Search, repository metadata, aggregate star count/history, rename redirect, 404/422, pagination, rate-limit header를 public read-only live request로 검증.
- 2026-10-10: `topic:ai` 4,131건 표본을 star 범위로 재귀 분할해 모든 leaf를 1,000건 이하로 만들 수 있음을 확인. star 범위는 inclusive이며 인접 구간은 `mid`/`mid+1`로 나눈다.
- 2026-10-10: PRD 21개 topic의 eligible `total_count`를 측정. 중복 포함 상한 6,426개 기준 daily Search는 약 78회 이상, 6시간 tracking은 보수적 2-call 기준 최대 12,852회/약 2.57시간으로 산정해 운영 가능하다고 판단.
- 2026-10-10: 유효한 `GITHUB_TOKEN`/`GH_TOKEN`이 없고 로컬 GitHub CLI credential도 무효하므로 인증 smoke test는 미실행. 유효한 read-only token으로 소형/중형/대형 요청과 인증 rate-limit header를 확인할 때까지 Phase 1은 `[!]`이며 Phase 2는 시작하지 않음.
- 2026-10-10: read-only fine-grained token이 GitHub CLI credential store에 설정된 후 인증 smoke test 완료. Search 30/minute, core 5,000/hour를 live header로 확인하고 소형 `octocat/Hello-World`, 중형 `fastapi/fastapi`, 대형 `freeCodeCamp/freeCodeCamp`의 metadata/count/history가 모두 HTTP 200임을 확인. token은 출력·문서화하지 않음.
- 2026-10-10: Phase 1 완료. 요청에 따라 Phase 2는 시작하지 않음.

## Phase 2 — 프로젝트 골격과 개발 품질 기준

**목표:** FastAPI/worker와 Next.js가 분리된 최소 실행 골격과 반복 가능한 개발 환경을 만든다.

**선행 조건:** Phase 1 통과

**상태:** `[x]` — 2026-10-10 완료

### 구현 항목

- [x] `uv` 기반 Python package, FastAPI app, worker entry point, test directory를 구성한다.
- [x] Next.js + TypeScript app을 구성한다.
- [x] PostgreSQL만 포함한 local Docker Compose를 구성한다.
- [x] 환경 변수 설정과 `.env.example`을 추가하되 실제 secret은 추가하지 않는다.
- [x] backend에 pytest, lint, type check를 위한 최소 dev dependency와 명령을 구성한다.
- [x] frontend에 test, lint, type check, build 명령을 구성한다. UI 단위 테스트에 필요한 최소 도구만 도입한다.
- [x] API 코드와 worker 코드의 entry point를 분리하되 동일 backend package와 domain code를 공유하게 한다.

### 완료 조건

- [x] 빈 FastAPI app과 Next.js app이 로컬에서 시작된다.
- [x] PostgreSQL 연결 설정을 환경 변수로 주입할 수 있다.
- [x] frontend/backend 품질 명령이 CI와 로컬에서 동일하게 실행 가능하다.
- [x] Redis, task queue, 범용 repository/service framework 등 불필요한 구성요소가 없다.

### 테스트 방법

- [x] backend unit test와 lint/type check를 실행한다.
- [x] frontend test, lint, type check, production build를 실행한다.
- [x] Docker Compose로 PostgreSQL을 시작하고 연결 smoke test를 실행한다.

### 실행 기록

- 2026-10-10: `uv sync` 성공. Python 3.12 환경과 `uv.lock`을 생성하고 FastAPI/worker/DB check entry point를 설치.
- 2026-10-10: `uv run pytest` — 4 passed, PostgreSQL integration 1 skipped (`TEST_DATABASE_URL` 미설정).
- 2026-10-10: `uv run ruff check .` — 통과. `uv run mypy` — 9 source files, 오류 없음.
- 2026-10-10: `npm test` — 1 passed. `npm run lint`, `npm run typecheck` — 통과. `npm run build` — Next.js 16.4.0 production build 성공.
- 2026-10-10: Uvicorn `/openapi.json` HTTP 200 및 Next.js production server `/` HTTP 200 기동 smoke 성공. worker entry point 실행 성공.
- 2026-10-10: `npm audit --omit=dev` — production dependency 취약점 0건. 전체 audit에는 `eslint-config-next`의 전이 `braces` 취약점 5건(high)이 남으며 안전한 non-breaking fix가 제공되지 않음.
- 2026-10-10: Docker Desktop WSL integration 활성화 후 `docker compose config --quiet` 통과, PostgreSQL 17 컨테이너 health check 성공.
- 2026-10-10: `TEST_DATABASE_URL=... uv run pytest -m integration` — 1 passed. `uv run repovil-db-check` — 연결 성공. PostgreSQL integration을 포함한 전체 `uv run pytest` — 5 passed.
- 2026-10-10: Phase 2 완료. 요청에 따라 Phase 3은 시작하지 않음.

## Phase 3 — Topic YAML 분리와 설정 검증

**목표:** PRD 3.1의 초기 Topic 매핑을 외부 설정으로 분리하고 안전하게 읽는다.

**선행 조건:** Phase 2

**상태:** `[x]` — 2026-10-11 완료

### 구현 항목

- [x] PRD 3.1의 YAML을 내용 변경 없이 `config/categories.yaml`에 저장한다.
- [x] `All`을 YAML category나 topic으로 추가하지 않는다.
- [x] category의 `name`, `slug`, `active`, `display_order`, `topics`를 검증하는 단순 loader를 구현한다.
- [x] 중복 category name/slug/display order, 중복 topic, 빈 topic 목록, 잘못된 slug를 명확한 오류로 거부한다.
- [x] YAML을 DB로 idempotent seed/sync하는 명령의 계약을 정하고 Phase 0에서 확정한 제거 정책을 적용한다.

### 완료 조건

- [x] 여섯 category와 모든 topic이 PRD와 동일하다.
- [x] 설정 오류가 부분 반영 없이 시작/명령 단계에서 실패한다.
- [x] 같은 설정을 반복 적용해도 중복 데이터가 생기지 않는다.

### 테스트 방법

- [x] 정상 YAML parsing 및 PRD 기대값 snapshot test를 실행한다.
- [x] 중복/누락/형식 오류 fixture에 대한 실패 테스트를 실행한다.
- [x] `All`이 설정 결과에 존재하지 않는지 확인한다.

### 실행 기록

- 2026-10-11: PRD 3.1과 동일한 6개 category/21개 topic을 `config/categories.yaml`에 추가하고, immutable Pydantic model과 safe YAML loader를 구현. `All`, 빈 설정/topic, 엄격하지 않은 타입, 잘못된 slug, 중복 name/slug/display order/topic을 전체 문서 적용 전에 거부하도록 구성.
- 2026-10-11: `docs/CATEGORY_SYNC_CONTRACT.md`에 Phase 4의 `repovil-sync-categories` 명령 경계, 단일 transaction, idempotent upsert, 제거 항목 soft-deactivate와 재활성화 정책을 확정. 실제 PostgreSQL sync 구현과 DB idempotency 검증은 계획대로 Phase 4 범위로 유지.
- 2026-10-11: `uv run repovil-categories-check` — 6 categories, 21 topics 검증 성공.
- 2026-10-11: `uv run pytest` — 21 passed, PostgreSQL integration 1 skipped (`TEST_DATABASE_URL` 미설정). `TEST_DATABASE_URL=... uv run pytest -m integration` — 1 passed.
- 2026-10-11: `uv run ruff check .` — 통과. `uv run mypy` — 11 source files, 오류 없음.
- 2026-10-11: Phase 3 완료. 요청에 따라 Phase 4는 시작하지 않음.

## Phase 4 — PostgreSQL schema와 Alembic migration

**목표:** PRD의 식별자, 이력 보존, run 단위 처리와 원자적 공개를 지원하는 최소 schema를 만든다.

**선행 조건:** Phase 3

**상태:** `[x]` — 2026-10-11 완료

### 구현 항목

- [x] PRD 핵심 테이블 `repositories`, `topics`, `categories`, `category_topics`, `repository_topics`를 migration으로 만든다.
- [x] `discovery_runs`, `tracking_runs`, `star_snapshots`, `bootstrap_star_history`, `rankings`를 migration으로 만든다.
- [x] tracking 시작 시 대상 확정과 repository별 success/failed/skipped 기록을 위한 최소 run-item 테이블을 추가한다. `(tracking_run_id, repository_id)`를 unique하게 한다.
- [x] `github_id UNIQUE`, run/repository 및 bootstrap 복합 key, ranking 복합 PK, `scheduled_at UNIQUE`를 구현한다.
- [x] `star_snapshots(repository_id, captured_at DESC)`와 읽기 endpoint에 필요한 최소 index를 추가한다.
- [x] timestamp는 timezone-aware PostgreSQL type으로 저장하고 애플리케이션 경계에서 UTC를 강제한다.
- [x] star count와 run count가 음수가 되지 않도록 제약하고 period/status 값은 PRD 값만 허용한다.
- [x] discovery 실패 구간을 재시도 가능한 구조로 저장한다. MVP에는 JSONB 또는 단순 child table 중 실제 query에 필요한 더 단순한 방식을 선택한다.
- [x] Phase 3의 category seed/sync를 transaction으로 DB에 적용한다.

### 완료 조건

- [x] 빈 PostgreSQL DB에 migration을 적용하면 PRD 데이터 모델과 제약이 생성된다.
- [x] repository rename/transfer가 owner/name 변경일 뿐 `github_id` identity를 바꾸지 않는다.
- [x] snapshot과 bootstrap 원천 row를 update/delete하지 않고 새 run을 누적할 수 있다.
- [x] run 대상, 결과, 공개 여부를 DB만으로 감사할 수 있다.

### 테스트 방법

- [x] 빈 DB에 `alembic upgrade head`를 실행한다.
- [x] downgrade 후 다시 upgrade하는 migration smoke test를 실행한다.
- [x] unique/FK/check constraint와 UTC round-trip integration test를 실행한다.
- [x] category seed/sync를 두 번 실행해 idempotency를 확인한다.

### 실행 기록

- 2026-10-11: Alembic 초기 migration으로 11개 MVP 테이블과 `github_id`, schedule slot, run/repository, bootstrap, ranking key 및 FK/check/index를 생성. tracking target/result용 `tracking_run_items`와 재시도 가능한 discovery 실패 구간용 JSONB 배열을 포함.
- 2026-10-11: 모든 timestamp를 PostgreSQL timezone-aware type으로 구성하고 공용 DB 연결과 migration session을 UTC로 고정. 격리 schema에서 rename identity 유지, 두 tracking run의 snapshot 누적, run item/result/publication 감사 및 UTC round-trip을 검증.
- 2026-10-11: `repovil-sync-categories`를 추가. 전체 YAML 선검증 후 단일 transaction에서 slug/name identity로 upsert하고 제거된 category/topic/mapping을 soft-deactivate하며 재추가 시 기존 ID로 복구. 반복 실행 시 row와 timestamp가 변하지 않고 DB 오류 시 전체 rollback됨을 검증.
- 2026-10-11: 격리 PostgreSQL schema에서 `upgrade → downgrade → upgrade` 및 unique/FK/check constraint 통합 테스트 통과. `TEST_DATABASE_URL=... uv run pytest` — 29 passed.
- 2026-10-11: `uv run ruff check .`, `uv run mypy` — 통과. Phase 4 완료, 요청에 따라 Phase 5는 시작하지 않음.

## Phase 5 — GitHubClient REST adapter

**목표:** Phase 1에서 검증한 GitHub REST API만 캡슐화하고 worker가 일관되게 오류와 rate limit을 처리하게 한다.

**선행 조건:** Phase 4

**상태:** `[x]` — 2026-10-11 완료

### 구현 항목

- [x] `search_repositories`, `get_repository`, `get_repository_stats`, `get_star_history`를 가진 최소 `GitHubClient`를 구현한다.
- [x] API version, auth header, timeout, user agent와 response parsing을 한 곳에서 관리한다.
- [x] pagination을 endpoint별 한계 안에서 구현한다.
- [x] timeout, connection error, 5xx, retry 가능한 403/429에 bounded exponential backoff를 적용한다.
- [x] 4xx를 not-found/자격 상태/인증 오류/rate limit/validation 오류로 구분하고 무한 재시도하지 않는다.
- [x] `Retry-After`와 `x-ratelimit-reset`을 우선하며, request별 rate-limit metadata를 worker가 기록할 수 있게 한다.
- [x] 구조화 로그 필드에 response status, retry count, duration을 제공하고 token은 redaction한다.
- [x] API/FastAPI request path에서 이 client를 import하거나 호출하지 못하도록 package 경계와 테스트를 둔다.

### 완료 조건

- [x] 모든 GitHub 호출이 `GitHubClient`를 통한다.
- [x] client는 DB나 ranking 정책을 알지 못한다.
- [x] 실패가 typed result/exception으로 worker에 전달되어 run 판정에 사용할 수 있다.
- [x] Phase 1 fixture로 응답 parsing이 재현된다.

### 테스트 방법

- [x] pagination, timeout, retry/backoff, 404, 422, 403/429, 5xx unit test를 실행한다.
- [x] rate-limit header와 `Retry-After` 우선순위 테스트를 실행한다.
- [x] API layer가 GitHubClient를 호출하지 않는 architecture test를 실행한다.
- [x] opt-in live smoke test로 Phase 1 endpoint를 다시 확인한다.

### 실행 기록

- 2026-10-11: 표준 라이브러리 기반 동기 `GitHubClient`와 worker 전용 생성 경계를 추가. 검증된 REST API version/auth/timeout/user-agent, endpoint별 pagination, redirect, 엄격한 metadata/count/history parsing을 한 곳에서 관리하고 DB/ranking 의존성은 두지 않음.
- 2026-10-11: timeout/connection/5xx/rate-limit에 제한된 exponential retry를 적용하고 `Retry-After` → `x-ratelimit-reset` → secondary-limit 60초 backoff 우선순위를 구현. 404, 인증, rate-limit, 422, 5xx, transport/response-format 실패를 typed exception으로 구분하고 성공/실패 모두 request metadata를 노출.
- 2026-10-11: response status, retry count, duration, rate-limit remaining 구조화 로그와 `SecretStr` 환경 설정을 추가. 로그와 예외에 token이 포함되지 않음을 검증하고 API import graph가 GitHubClient에 도달하지 않는 architecture test를 추가.
- 2026-10-11: `GITHUB_LIVE_TEST=1 uv run pytest backend/tests/test_github_client.py::test_live_verified_public_endpoints -q` — public read-only Search, repository metadata와 rename redirect, count, history 모두 통과(1 passed).
- 2026-10-11: `TEST_DATABASE_URL=... uv run pytest` — 57 passed, live 1 skipped. `uv run ruff check .`, `uv run mypy`, `git diff --check` — 모두 통과.
- 2026-10-11: Phase 5 완료. 요청에 따라 Phase 6은 시작하지 않음.

## Phase 6 — Discovery worker

**목표:** 설정 topic별 repository를 매일 발견하고, 완전하지 않은 검색을 성공으로 숨기지 않으며, `github_id` 기준으로 저장한다.

**선행 조건:** Phase 5

**상태:** `[x]` — 2026-10-11 완료

### 구현 항목

- [x] 활성 topic 각각에 대해 public, non-fork, non-archived, stars 200 이상 Search를 실행한다.
- [x] 1,000건 초과 star 구간을 재귀 분할하고, 경계 중복은 `github_id`로 제거한다.
- [x] `incomplete_results`, pagination/search 실패, rate limit, 더 분할할 수 없는 과다 구간을 실패 구간으로 저장한다.
- [x] 실패 구간만 안전하게 재시도할 수 있게 하고, 미완료 run을 정상 완료로 표시하지 않는다.
- [x] 결과를 다시 eligibility 검증한 뒤 신규 repository를 저장하고 기존 metadata와 topic을 갱신한다.
- [x] 같은 repository가 여러 topic/category에 속하는 것을 보존한다.
- [x] `github_id` 기준 upsert로 rename/transfer 시 owner/name/url을 갱신한다.
- [x] 신규 eligible repository는 bootstrap 대기 상태로 저장하고 Phase 7 성공 후 tracking 대상으로 활성화한다.
- [x] discovery job 중복 실행을 PostgreSQL lock/run 상태로 방지한다.
- [x] run별 시작/종료, 발견 수, 추가 수, 상태, 실패 구간을 구조화 로그와 DB에 기록한다.

### 완료 조건

- [x] 같은 결과를 반복 처리해도 repository와 관계가 중복되지 않는다.
- [x] 일부 topic/구간 실패가 성공으로 기록되지 않고 재실행 가능하다.
- [x] stars 200 미만 repository는 최초 저장되지 않는다.
- [x] multi-category repository가 한 repository row와 여러 topic 관계로 저장된다.

### 테스트 방법

- [x] 중복 discovery와 여러 topic 중복 결과 테스트를 실행한다.
- [x] 999/1,000/1,001건 구간, inclusive boundary, 단일 star 과다 구간 테스트를 실행한다.
- [x] `incomplete_results`, 중간 page 실패, rate limit 후 재시도 테스트를 실행한다.
- [x] 신규/기존/rename/transfer metadata update integration test를 실행한다.
- [x] 동시 실행 시 하나만 진행되는 DB lock test를 실행한다.

### 실행 기록

- 2026-10-11: `repovil-discovery` worker를 추가. DB의 활성 category/topic만 대상으로 GitHub Search를 실행하고, 1,000건 초과 범위를 inclusive 경계가 겹치지 않게 재귀 분할하며 `github_id`로 결과를 중복 제거하도록 구현.
- 2026-10-11: public/non-fork/non-archived/stars 200 이상과 활성 topic 교집합을 저장 전에 재검증. 신규 repository는 `bootstrap_pending`, 기존 identity는 metadata/topic을 갱신하고 inactive repository의 재발견은 기존 history를 유지한 채 재활성화하도록 구성.
- 2026-10-11: `incomplete_results`, pagination/API/rate-limit 실패와 단일 star 과다 구간을 request metadata가 포함된 JSONB 실패 구간으로 보존. `--retry-run`은 해당 run의 활성 topic 실패 구간만 새 run으로 재실행하며, PostgreSQL session advisory lock으로 중복 실행을 차단.
- 2026-10-11: 999/1,000/1,001건, inclusive 분할, 단일 star 과다, incomplete/middle-page/rate-limit 실패, 중복/multi-topic/eligibility/rename/reactivation, 실패 구간 재실행, DB lock 테스트 추가. `TEST_DATABASE_URL=... uv run pytest` — 66 passed, live 1 skipped.
- 2026-10-11: `uv run ruff check .`, `uv run mypy`, `git diff --check` 및 `repovil-discovery --help` smoke — 모두 통과. Phase 6 완료, 요청에 따라 Phase 7은 시작하지 않음.

## Phase 7 — Historical bootstrap

**목표:** 신규 repository의 7d/30d ranking과 30일 graph에 사용할 추정 원천 데이터를 수집·보존한다.

**선행 조건:** Phase 6

**상태:** `[x]` — 2026-10-11 완료

### 구현 항목

- [x] 신규 eligible repository에 대해 `get_star_history`를 호출해 필요한 최근 구간의 일별 `stars_created`를 저장한다.
- [x] `(repository_id, date)` 기준 idempotent upsert와 `fetched_at` 기록을 구현한다.
- [x] 최신 실측 star count에서 일별 생성 수를 역산해 7d/30d baseline 후보를 계산한다.
- [x] API의 일 경계가 UTC와 정확히 일치하지 않음을 유지하고 결과를 항상 `is_estimated=true`로 표시할 수 있게 한다.
- [x] unstar를 복원하지 못하는 추정치임을 domain model과 API contract에 반영한다.
- [x] 음수 baseline, 누락/불연속 응답 등 유효하지 않은 추정치는 사용하지 않는다.
- [x] bootstrap은 24h baseline에 절대 사용하지 않는다.
- [x] bootstrap 성공 후 tracking을 활성화한다. 실패는 원인과 재시도 상태를 남기고 snapshot/ranking으로 위장하지 않는다.

### 완료 조건

- [x] 유효한 신규 repository가 7d/30d 추정 baseline 후보를 갖는다.
- [x] 원천 일별 데이터와 계산 결과를 분리해 재계산할 수 있다.
- [x] 자체 snapshot이 충분해지면 ranking이 자동으로 실제 baseline을 우선할 수 있다.
- [x] 잘못된 추정치가 ranking이나 graph에 포함되지 않는다.

### 테스트 방법

- [x] known daily counts에서 7d/30d baseline 역산 테스트를 실행한다.
- [x] unstar로 최신 count와 누적 생성 수가 어긋나는 fixture를 테스트한다.
- [x] 음수, 누락, page 경계, 중복 fetch, API 실패 테스트를 실행한다.
- [x] 24h 계산 경로가 bootstrap을 참조하지 않는 테스트를 실행한다.

### 실행 기록

- 2026-10-11: `repovil-bootstrap` worker를 추가. `bootstrap_pending` repository의 최신 star count와 GitHub 주간 history를 수집해 최근 30일 일별 원천 row를 보존하고, 성공 시 tracking을 활성화하도록 구현.
- 2026-10-11: 7d/30d 전용 추정 baseline domain model과 계산을 추가. provider 일 경계와 unstar 한계를 유지해 항상 `is_estimated=true`로 표시하며, 누락·불연속·음수 추정은 생성하지 않고 24h 요청은 명시적으로 거부.
- 2026-10-11: bootstrap 시도/완료/실패와 request metadata를 기록하는 Alembic migration을 추가. API/응답 형식 실패는 `bootstrap_pending` 상태와 원인을 보존해 다음 실행에서 재시도하며, 원천 row 충돌 시 기존 값을 덮어쓰지 않음.
- 2026-10-11: known counts, unstar 한계, 음수/누락, 주간 page 경계, 중복 fetch, API 실패 후 재시도, advisory lock 테스트 추가. `TEST_DATABASE_URL=... uv run pytest` — 76 passed, live 1 skipped.
- 2026-10-11: migration `upgrade → downgrade → upgrade`, `uv run ruff check .`, `uv run mypy`, `git diff --check`, `repovil-bootstrap --help` — 모두 통과. Phase 7 완료, 요청에 따라 Phase 8은 시작하지 않음.

## Phase 8 — Tracking 및 snapshot worker

**목표:** 6시간마다 대상 집합을 고정하고 성공한 실제 측정만 snapshot으로 보존한다.

**선행 조건:** Phase 7

**상태:** `[x]` — 2026-10-11 완료

### 구현 항목

- [x] UTC schedule slot을 `scheduled_at`으로 사용해 idempotent `tracking_run`을 만들고 PostgreSQL 기반 중복 실행 방지를 적용한다.
- [x] run 시작 시 활성 tracking 대상 전체를 run-item으로 확정한다.
- [x] 각 대상의 current star 수, metadata, topics와 eligibility를 GitHubClient로 확인한다.
- [x] 실제 응답 측정 시각을 `captured_at`으로 저장하고 scheduler 예정 시각으로 대체하지 않는다.
- [x] 성공한 repository만 해당 run snapshot을 저장한다.
- [x] transient 실패는 failed로 기록하고 이전 snapshot을 현재 run의 값으로 복사하지 않는다.
- [x] stars 200 미만, archived, private, deleted, 모든 설정 topic 이탈을 확인하면 기록은 유지한 채 tracking/publication에서 비활성화한다.
- [x] 비활성 repository가 이후 discovery에서 자격을 다시 만족하면 재활성화한다.
- [x] repository별 success/failed/skipped와 오류, retry count, duration을 기록한다.
- [x] `COMPLETED`, `PARTIAL`, `FAILED`를 PRD 정의대로 계산한다. publication은 다음 Phase에서 별도로 판정한다.

### 완료 조건

- [x] 같은 schedule slot 재실행이 중복 run/snapshot을 만들지 않는다.
- [x] target 목록은 run 도중 discovery 변경의 영향을 받지 않는다.
- [x] 실패 대상에 stale snapshot이 생성되지 않는다.
- [x] rename과 자격 상실/재활성화가 history를 잃지 않고 `github_id` 동일성을 유지한다.

### 테스트 방법

- [x] 전체 성공, 일부 실패, 전부 실패, 분모 0 run 테스트를 실행한다.
- [x] timeout/retry exhaustion 시 stale snapshot 미생성 테스트를 실행한다.
- [x] rename, stars 하락, archived/private/deleted/topic 이탈 및 재활성화 테스트를 실행한다.
- [x] concurrent/duplicate schedule 실행과 unique constraint 테스트를 실행한다.
- [x] captured_at이 실제 측정 시각이며 UTC로 보존되는지 확인한다.

### 실행 기록

- 2026-10-11: `repovil-tracking` worker를 추가. 현재 시각을 6시간 UTC slot으로 정규화하고 `scheduled_at` uniqueness와 PostgreSQL advisory lock으로 중복 실행을 막으며, run 생성 시 활성 repository 전체를 run-item으로 확정하도록 구현.
- 2026-10-11: repository metadata/topic/identity와 별도 current star count를 `GitHubClient`로 확인하고 성공 응답 직후의 실제 UTC 시각만 snapshot으로 저장. rename/transfer metadata와 topic 관계를 같은 `github_id` row에 갱신하고 실패 시 과거 snapshot을 복사하지 않음.
- 2026-10-11: stars 하락, archived/private/deleted/fork/topic 이탈과 run 도중 비활성화는 `skipped`로 기록해 repository/history를 보존하고 inactive 전환. transient 오류는 `failed`, 인증 오류는 미처리 대상까지 failed로 종결하며 item별 status/error/response/retry/duration을 감사 가능하게 저장.
- 2026-10-11: 전체 성공/일부 실패/전부 실패/분모 0, stale snapshot 금지, rename/topic 갱신, 각 eligibility 상실, 고정 target, 중복 slot, concurrent lock, 실제 captured_at 테스트 추가. 기존 discovery 재활성화 회귀 테스트를 포함한 `TEST_DATABASE_URL=... uv run pytest` — 91 passed, live 1 skipped.
- 2026-10-11: `uv run ruff check .`, `uv run mypy`, `git diff --check`, `repovil-tracking --help` — 모두 통과. Phase 8 완료, 요청에 따라 Phase 9는 시작하지 않음.

## Phase 9 — Ranking 계산과 원자적 공개

**목표:** PRD 공식과 baseline 정책으로 ranking을 계산하고 품질 기준을 만족한 run만 한 번에 공개한다.

**선행 조건:** Phase 8

**상태:** `[x]` — 2026-10-11 완료

### 구현 항목

- [x] 각 repository의 실제 `captured_at`에서 24h/7d/30d `target_time`을 계산한다.
- [x] target 이전의 가장 가까운 자체 snapshot이며 target과 차이가 최대 6시간인 경우만 실제 baseline으로 선택한다.
- [x] 실제 baseline이 없을 때 7d/30d만 유효한 bootstrap baseline으로 fallback하고 `is_estimated=true`를 저장한다.
- [x] 24h는 실제 baseline이 없으면 제외한다.
- [x] `star_gain = current - baseline`, `score = ln((current+1)/(baseline+1))`를 구현하고 `star_gain > 0`만 저장한다.
- [x] 정렬을 `score DESC → star_gain DESC → github_id ASC`로 고정한다.
- [x] tracking 성공률을 `success / (success + failed)`로 계산하고 skipped는 분모에서 제외한다.
- [x] 분모가 0이면 공개하지 않고, 성공률 95% 이상일 때만 ranking 전체 생성과 `published_at` 설정을 하나의 DB transaction으로 수행한다.
- [x] 95% 미만이거나 계산/transaction이 실패하면 직전 공개 run을 유지한다.
- [x] 카테고리별 ranking을 복제 저장하지 않고 topic mapping join으로 조회하며 repository 중복을 제거한다.

### 완료 조건

- [x] 세 기간의 ranking이 PRD 공식과 baseline 허용 오차를 정확히 따른다.
- [x] 일부 실패 run도 95% 이상이면 공개할 수 있고, 미만이면 공개되지 않는다.
- [x] API가 읽는 published run에는 ranking 전체가 있거나 전혀 없다.
- [x] `rankings.current_stars`가 공개 run의 snapshot과 일치한다.

### 테스트 방법

- [x] target 직전/정확히 6시간/6시간 초과 baseline 선택 테스트를 실행한다.
- [x] 24h bootstrap 금지, 7d/30d fallback, invalid bootstrap 제외 테스트를 실행한다.
- [x] star 감소/0 gain 제외와 score 수치 테스트를 실행한다.
- [x] score 동점, gain 동점, 최종 `github_id` 동점 해소 테스트를 실행한다.
- [x] 94.99%, 95%, 100%, 분모 0 publication 판정 테스트를 실행한다.
- [x] transaction 중 실패 시 직전 published run 유지 테스트를 실행한다.
- [x] multi-topic category join 중복 제거 테스트를 실행한다.

### 실행 기록

- 2026-10-11: 실제 snapshot의 `captured_at` 기준 24h/7d/30d target과 최대 6시간 허용 오차를 적용하는 ranking domain을 추가. 실제 baseline을 우선하고 7d/30d만 bootstrap 추정 fallback을 허용하며, 양의 gain과 PRD score/정렬 규칙을 구현.
- 2026-10-11: tracking 종료 직후 성공률을 정수 산술로 판정하고 ranking 전체 삽입과 `published_at` 갱신을 단일 transaction으로 수행하도록 연결. 95% 미만·분모 0·실행 자체 실패는 공개하지 않으며, 공개 transaction 실패 후 동일 slot 재실행은 GitHub 재호출 없이 공개만 재시도 가능하게 구성.
- 2026-10-11: category topic 관계는 `EXISTS` join으로 조회해 여러 matching topic을 가진 repository도 한 번만 반환하고 `score DESC → star_gain DESC → github_id ASC` 순서를 고정.
- 2026-10-11: baseline 경계, bootstrap 제한/우선순위, gain/score/동점, 94.99%/95%/100%/분모 0, exact-95% partial 공개, transaction rollback, multi-topic 중복 제거 테스트 추가. `TEST_DATABASE_URL=... uv run pytest` — 112 passed, live 1 skipped.
- 2026-10-11: `uv run ruff check .`, `uv run mypy`, `git diff --check` — 모두 통과. Phase 9 완료, 요청에 따라 Phase 10은 시작하지 않음.

## Phase 10 — FastAPI 읽기 전용 API

**목표:** GitHub를 호출하지 않고 PostgreSQL의 마지막 공개 데이터만 안정적으로 제공한다.

**선행 조건:** Phase 9

**상태:** `[x]` — 2026-10-11 완료

### 구현 항목

- [x] `GET /rankings`에 period/category/page validation, 20개 pagination, PRD 정렬을 구현한다.
- [x] 마지막 `published_at`이 있는 run만 읽고 `tracking_run_id`, `calculated_at`, page 정보를 반환한다.
- [x] 공개 run이 없을 때 빈 ranking과 구분되는 명시적 데이터 준비 중 응답을 구현한다.
- [x] category 미지정을 `All`로 처리하고 DB에 `All` row를 만들지 않는다.
- [x] `GET /categories`가 활성 category를 `display_order` 순으로 모두 반환하며 결과 0건 category도 누락하지 않게 한다.
- [x] `GET /repositories/{owner}/{name}`에 현재 metadata와 GitHub link를 구현한다.
- [x] `GET /repositories/{owner}/{name}/star-history`에 최근 30일 실제 snapshot/bootstrap point와 점별 추정 여부를 구현한다.
- [x] 실제 snapshot과 bootstrap이 겹치면 실제 값을 우선하고 bootstrap을 실제값으로 표시하지 않는다.
- [x] `GET /health`는 process liveness, `GET /ready`는 DB 등 필수 의존성 readiness를 반환한다.
- [x] user-facing API가 GitHubClient 또는 외부 network를 호출하지 않음을 보장한다.

### 완료 조건

- [x] 네 endpoint와 health/readiness가 PRD 응답 상태를 구분한다.
- [x] ranking page는 정확히 20개 단위이며 안정적인 정렬과 총 page 정보를 제공한다.
- [x] category filter가 multi-topic repository를 중복 반환하지 않는다.
- [x] API 데이터가 항상 공개 run/snapshot provenance를 유지한다.

### 테스트 방법

- [x] period/category/page 정상·오류 및 첫/중간/마지막/범위 밖 page 테스트를 실행한다.
- [x] published run 없음, 빈 결과, category 0건 테스트를 실행한다.
- [x] 동점 정렬과 category 중복 제거 integration test를 실행한다.
- [x] rename 후 현재 owner/name 상세 조회와 not-found 테스트를 실행한다.
- [x] 30일 경계, estimated/actual 혼합, actual 우선 history 테스트를 실행한다.
- [x] API 요청 중 outbound GitHub call이 0회인지 테스트한다.
- [x] DB 정상/비정상 readiness 테스트를 실행한다.

### 실행 기록

- 2026-10-11: PostgreSQL 전용 FastAPI 읽기 API를 구현. 마지막 공개 run의 24h/7d/30d ranking, 활성 category 검증, 고정 20개 pagination, PRD 동점 정렬과 multi-topic 중복 제거를 제공하고 `preparing`과 ready 빈 결과를 구분.
- 2026-10-11: 활성 category 전체 조회, 현재 repository metadata/rename 조회, 동일한 `repository_not_found` 404 계약, 최근 30일 actual/bootstrap history와 날짜 중첩 시 actual 우선 처리를 추가. health는 DB 비의존, readiness는 PostgreSQL 연결 상태를 반영.
- 2026-10-11: API import graph에서 ranking/GitHubClient 의존성을 제거해 사용자 요청 경로가 외부 network 없이 DB만 읽도록 유지. HTTP 통합 테스트를 위해 현재 Starlette가 요구하는 `httpx2`를 개발 의존성으로 추가.
- 2026-10-11: `TEST_DATABASE_URL=... uv run pytest` — 121 passed, live 1 skipped. `uv run ruff check .`, `uv run mypy`, `git diff --check` — 모두 통과.
- 2026-10-11: Phase 10 완료. 요청에 따라 Phase 11은 시작하지 않음.

## Phase 11 — Next.js ranking 화면

**목표:** 사용자가 공개 ranking을 기간과 category로 조회할 수 있게 한다.

**선행 조건:** Phase 10

**상태:** `[x]` — 2026-10-11 완료

### 구현 항목

- [x] `All` 및 활성 category filter와 `24h | 7d | 30d` period filter를 구현한다.
- [x] URL query에 period/category/page 상태를 반영해 새로고침과 공유가 가능하게 한다.
- [x] 각 항목에 owner/name, 설명, star 수, growth score, star gain, 언어, category, GitHub link를 표시한다.
- [x] 20개 단위 pagination UI를 구현한다.
- [x] 공개 ranking 없음의 데이터 준비 중 상태와 정상 빈 결과를 구분한다.
- [x] 결과가 0개인 활성 category도 filter에서 유지한다.
- [x] loading, API error, retry 가능한 화면 상태와 기본 접근성을 구현한다.

### 완료 조건

- [x] 모든 filter 조합과 pagination이 API 계약과 일치한다.
- [x] 외부 GitHub link와 repository 상세 navigation이 동작한다.
- [x] 데이터 준비 중, 빈 결과, 오류가 서로 다른 사용자 상태로 표시된다.
- [x] 브라우저에서 GitHub API를 직접 호출하지 않는다.

### 테스트 방법

- [x] filter/query-string/pagination component test를 실행한다.
- [x] 0건 category, 준비 중, API 오류 rendering test를 실행한다.
- [x] 항목 필드와 link rendering test를 실행한다.
- [x] frontend lint, type check, production build를 실행한다.
- [x] desktop/mobile viewport에서 수동 smoke test를 실행한다.

### 실행 기록

- 2026-10-11: Next.js 서버 컴포넌트 기반 ranking 화면을 구현. `All`/활성 category와 24h/7d/30d filter, URL query 상태, 20개 pagination, repository/GitHub link, 공개 시각과 ranking 필드를 FastAPI 응답에 연결.
- 2026-10-11: 준비 중·정상 빈 결과·loading·API error/retry 화면을 분리하고 skip link, navigation label, focus style, `aria-current`와 reduced-motion 처리를 추가. 서버 전용 `REPOVIL_API_URL` fetch로 브라우저의 FastAPI/GitHub 직접 호출을 방지.
- 2026-10-11: filter/query/pagination, 0건 category, 준비 중/빈 결과/API 오류, 항목 필드/link, loading/retry 접근성 테스트 추가. `npm test` — 9 passed. `npm run lint`, `npm run typecheck`, `npm run build` — 모두 통과.
- 2026-10-11: production server와 mock FastAPI를 기동해 `/?period=24h&category=skills&page=1`의 HTTP 200을 확인. Chromium 1440x1000/390x844 viewport에서 선택 filter, 6개 repository 카드, 상세 link, 가로 overflow 없음과 desktop/mobile screenshot을 수동 검토.
- 2026-10-11: Docker PostgreSQL 연결 복구 후 integration과 read-only GitHub live smoke를 포함한 `TEST_DATABASE_URL=... GITHUB_LIVE_TEST=1 uv run pytest` — 122 passed, skipped 없음. `repovil-db-check` 연결 smoke도 통과.
- 2026-10-11: Phase 11 완료. 요청에 따라 Phase 12는 시작하지 않음.

## Phase 12 — Repository 상세와 30일 star graph

**목표:** repository metadata와 최근 30일 star 추이를 실제/추정 구분과 함께 보여준다.

**선행 조건:** Phase 11

**상태:** `[x]` — 2026-10-11 완료

### 구현 항목

- [x] owner/name route의 상세 metadata와 GitHub link를 구현한다.
- [x] 최근 30일 star graph를 구현한다.
- [x] 실제 snapshot과 bootstrap 추정 point를 색상/선 스타일/범례 등 시각적으로 구분한다.
- [x] 30일 경계, 일부 데이터, 전부 실제, 실제+추정 혼합, 빈 history 상태를 처리한다.
- [x] graph에 접근 가능한 label/summary와 추정치 설명을 제공한다.
- [x] rename 이후 현재 route가 동작하도록 API의 현재 metadata를 사용한다.

### 완료 조건

- [x] 사용자가 실제값과 추정값을 혼동하지 않고 구분할 수 있다.
- [x] 최근 30일 밖의 점은 표시하지 않는다.
- [x] bootstrap 누락 또는 일부 수집 실패가 page 전체 오류를 만들지 않는다.

### 테스트 방법

- [x] actual-only, estimated-only, mixed, empty fixture component test를 실행한다.
- [x] 30일 경계와 actual 우선 표시 테스트를 실행한다.
- [x] 상세 not-found와 API 오류 상태 테스트를 실행한다.
- [x] frontend lint, type check, production build를 실행한다.
- [x] graph 범례와 접근성을 수동 검증한다.

### 실행 기록

- 2026-10-11: `/repositories/{owner}/{name}` Next.js 상세 route를 추가. FastAPI의 현재 metadata를 사용해 rename/transfer 이후 identity, 설명, star 수, 언어/category/status, 발견·tracking 시각과 GitHub 링크를 표시하고 API 404를 전용 not-found 상태로 분리.
- 2026-10-11: 의존성 없는 server-rendered SVG 30일 star graph를 구현. actual은 파란 실선, bootstrap estimate는 녹색 점선과 개별 point/범례로 구분하고, 30일 범위 방어 검증·동일 날짜 actual 우선·빈 history를 처리. 화면 요약, SVG title/description, 점별 title과 screen-reader용 데이터 표 및 추정 한계 설명을 추가.
- 2026-10-11: actual-only/estimated-only/mixed/empty, 30일 inclusive 경계·범위 밖 제외·actual 우선, 현재 rename metadata, API loading/error/not-found와 read-only fetch 테스트 추가. `npm test` — 18 passed. `npm run lint`, `npm run typecheck`, `npm run build`, `git diff --check` — 모두 통과.
- 2026-10-11: production build와 mock read-only API를 연결해 Chromium 1440x1000/390x844에서 상세 route HTTP 200, actual/estimated 범례, 16개 graph point, 접근성 label 연결과 문서 가로 overflow 없음 확인. Phase 12 완료, 요청에 따라 Phase 13은 시작하지 않음.

## Phase 13 — Railway 운영 구성과 관찰 가능성

**목표:** API/web과 두 worker schedule을 Railway에서 안전하고 재실행 가능하게 운영한다.

**선행 조건:** Phase 12

**상태:** `[x]` — 2026-10-13 Railway staging `Run now`로 tracking publication과 daily 전체 pipeline 재검증 완료

### 구현 항목

- [x] Railway의 web/API service와 동일 backend codebase의 worker entry point를 구성한다.
- [x] PostgreSQL과 네 service의 build/deploy/variable 관계를 단일 Railway IaC 파일로 선언하고 legacy Config as Code를 제거한다.
- [x] daily discovery와 6시간 tracking/ranking을 별도 Railway Cron으로 구성한다.
- [x] deploy/release 시 Alembic migration 실행 순서와 실패 시 중단 절차를 문서화한다.
- [x] DB URL, GitHub token, API version 등 secret/config를 Railway 환경 변수로만 주입한다.
- [x] UTC schedule과 애플리케이션 UTC 설정을 명시한다.
- [x] `run_id`, `repository_id`, response status, retry count, duration을 포함한 구조화 로그를 구현한다.
- [x] 실패 run/구간의 안전한 수동 재실행 절차를 문서화한다.
- [x] health/readiness와 cron exit code가 Railway에서 실패를 식별하게 한다.

### 완료 조건

- [x] 중복 cron 실행이 DB guard에 의해 차단된다.
- [x] worker 실패가 published ranking을 손상시키지 않고 non-zero exit/log로 관찰된다.
- [x] secret이 repository, image, log에 노출되지 않는다.
- [x] 운영자가 discovery 실패 구간과 tracking partial failure를 run id로 추적할 수 있다.

### 테스트 방법

- [x] Railway와 동일한 command로 API, discovery, tracking을 staging에서 smoke test한다.
- [x] 동일 scheduled slot 동시 실행 테스트를 수행한다.
- [x] 의도적 부분 실패에서 exit/status/log/published ranking 유지 여부를 확인한다.
- [x] migration, health, readiness, 환경 변수 누락 실패를 확인한다.
- [x] secret scan과 로그 redaction 점검을 수행한다.

### 실행 기록

- 2026-10-11: backend/web multi-stage Docker image와 API/web/daily/tracking 배포 설정을 추가. Daily는 `0 3 * * *`, tracking/ranking은 `0 */6 * * *` UTC cron이며, daily command는 discovery 실패를 보존하면서 pending bootstrap도 시도하도록 구성.
- 2026-10-11: Railway `PORT`, 필수 variable 선검증, 한 줄 JSON logging과 허용 필드 기반 secret 차단을 구현. Discovery `PARTIAL`/`FAILED`, bootstrap repository 실패, tracking `PARTIAL`/`FAILED`를 non-zero exit로 노출하고 기존 DB status 및 95% 원자적 공개 정책은 변경하지 않음.
- 2026-10-11: `docs/RAILWAY_OPERATIONS.md`에 migration-first release, health/readiness, UTC, secret/reference variable, rollback, run id 조회 및 discovery/bootstrap/tracking 수동 재실행 절차를 기록.
- 2026-10-11: 종료 예정인 service별 Railway Config as Code를 제거하고 `.railway/railway.ts` 단일 IaC로 PostgreSQL, API, web, daily, tracking의 source/build/deploy/reference variable을 선언. `railway` SDK 3.13.1을 고정하고 타입 검사와 3개 리소스 그래프 테스트를 추가했으며, staging plan/apply 순서를 운영 문서에 기록.
- 2026-10-11: `docker build`로 backend/web production image를 빌드. backend image에서 Alembic upgrade와 category sync, 빈 대상 tracking command 성공, `PORT=4567` API `/health`·`/ready` HTTP 200, 잘못된 DB에서 `/ready` HTTP 503 확인. web standalone image를 API에 연결해 `/` HTTP 200 확인. backend/web 필수 variable 누락 시 JSON 오류와 exit 1 확인.
- 2026-10-11: `TEST_DATABASE_URL=... uv run pytest` — 131 passed, GitHub live 1 skipped. Railway IaC graph test 3 passed. `uv run ruff check .`, `uv run mypy`, frontend `npm test` — 18 passed, `npm run lint`, `npm run typecheck`, `npm run build`, root `npm audit`, `git diff --check`, secret pattern scan 통과.
- 2026-10-11: GitHub 연동 이후에도 실제 Railway staging plan/apply/smoke는 실행하지 않음. 외부 리소스 생성과 배포는 사용자가 plan을 검토하고 승인해야 하므로 Phase 13을 `[!]`로 유지하며 Phase 14는 시작하지 않음.
- 2026-10-11: 승인된 staging plan(`5 add / 0 change / 0 destroy`)을 적용해 PostgreSQL과 API/web/daily/tracking service를 생성. Dockerfile service의 custom command가 exec form으로 실행되어 `&&` 뒤 명령이 시작되지 않는 실제 배포 실패를 확인하고, API pre-deploy/start와 두 Cron start를 명시적 `/bin/sh -c`로 수정한 뒤 IaC type check와 graph test 3개를 통과시킴.
- 2026-10-11: 수정 plan(`0 add / 4 change / 0 destroy`)을 staging에 적용. Alembic migration 2개와 category sync(6 categories, 21 topics)가 성공하고 네 service deployment가 모두 `SUCCESS`가 됨. API/web public domain을 생성해 API `/health`, `/ready`, `/categories`와 web `/` HTTP 200을 확인. Railway가 API/web의 기본 `ON_FAILURE` restart policy를 저장 시 기본값으로 정규화해 반복 drift로 표시하므로, 동일 동작의 platform default를 사용하고 Cron의 `NEVER`만 명시적으로 유지. 실제 scheduled command 종료 검증은 tracking의 2026-10-11 12:00 UTC 첫 실행과 daily의 2026-10-12 03:00 UTC 첫 실행 후 확인해야 하므로 Phase 13은 `[!]`로 유지.
- 2026-10-12: Railway staging의 첫 scheduled tracking(2026-10-11 12:00 UTC)과 daily(2026-10-12 03:00 UTC)를 확인. 두 deployment 모두 `CRASHED`였고 각각 12:03:46 UTC, 03:04:14 UTC에 worker 선검증이 빈 `GITHUB_TOKEN`을 `missing_variables`로 기록한 뒤 실제 worker 진입 전에 종료. 두 service에는 `GITHUB_TOKEN` 키가 있으나 해석된 값은 공백이었다. DB-backed API는 `/ready`가 ready이고 category 6개를 반환했지만 `/rankings?period=7d`는 `tracking_run_id=null`인 `preparing` 상태였다. Phase 13은 `[!]`로 유지하고 Phase 14는 시작하지 않음.
- 2026-10-13: Railway staging의 scheduled tracking(2026-10-12 06:00 UTC, 15:00 KST)은 run 1이 `COMPLETED`로 06:02:32 UTC 종료됐고 대상·success·failed·skipped가 모두 0이었다. `tracking_run_items`, `star_snapshots`, `rankings`도 모두 0건이며 공개 분모가 0이므로 `published_at=NULL`인 것은 95% 정책과 일치한다. 이후 scheduled run들이 실행된 점과 terminal summary로 process 종료도 확인했다.
- 2026-10-13: scheduled daily(2026-10-13 03:00 UTC, 12:00 KST)는 03:00:42 UTC 시작 후 discovery run 1이 03:03:51 UTC `PARTIAL`로 종료됐다. 3,498개를 발견·추가했지만 `mcp-server`, `mcp-servers`, `rag`, `retrieval-augmented-generation`, `vector-database`의 5개 range가 모두 `GitHubRateLimitError`/HTTP 403/retry 3으로 실패했다. Bootstrap은 3,498개 중 3,485개를 완료했고 나머지 13개가 같은 `GitHubRateLimitError`/HTTP 403/retry 3으로 `bootstrap_pending`에 남았다. `daily_pipeline_finished=FAILED` 후 Railway instance가 `CRASHED`로 종료됐으므로 정상 성공이 아니다.
- 2026-10-13: 추가 scheduled tracking(2026-10-13 06:00 UTC, 15:00 KST)은 run 5가 06:26:22 UTC `COMPLETED`로 종료됐고 3,485 success / 0 failed / 0 skipped였다. DB에서 run item 3,485건과 snapshot 3,485건이 repository별 1:1이며 pending, success-without-snapshot, non-success-with-snapshot, orphan은 모두 0이었다. 그러나 log가 `published 6252 rankings`라고 보고한 것과 달리 재접속한 DB에는 `published_at=NULL`, ranking 0건이고 API도 `preparing`이었다. 성공률 100%인데 공개되지 않아 95% 정책을 위반한다. 원인은 `_finish_run()`의 `_run_result()` SELECT가 연 implicit transaction 안에서 `publish_rankings()`의 nested transaction만 완료된 뒤 `finally`의 `connection.rollback()`이 publication insert/update를 되돌리는 transaction 경계 결함이다. Railway process 자체는 exit 0으로 `SUCCESS`/`EXITED`였지만 data-level 성공은 아니다.
- 2026-10-13: 위 세 실행 구간의 구조화 로그를 staging에서 해석된 실제 `GITHUB_TOKEN`·`DATABASE_URL` 값 및 token/URL/header 패턴과 대조해 노출 0건을 확인했다. DB에는 RUNNING 상태의 discovery/tracking run과 orphan snapshot/ranking이 없다. 다음 조치는 publication을 명시적으로 commit하도록 수정하고 별도 connection 재조회 regression test를 추가한 뒤 staging에 배포해 run 5의 동일 slot publication 재시도와 DB/API 확인을 수행하는 것이다. GitHub rate limit reset 후 discovery run 1의 실패 range와 bootstrap pending 13건을 재실행하고 다음 실제 scheduled daily/tracking까지 성공·종료를 다시 확인한다. 그때까지 Phase 13은 `[!]`로 유지하고 Phase 14는 시작하지 않는다.
- 2026-10-13: 재검증 대기 시간을 줄이되 운영 계약을 바꾸지 않도록, UTC schedule 기동은 이미 관찰한 실제 예약 실행으로 증명하고 worker-only 수정은 동일 image/start command/variable의 Railway `Run now`로 즉시 검증하기로 결정. 검증용 임시 schedule 변경은 하지 않는다. tracking은 완료됐지만 미공개인 동일 slot의 publication만 재시도해 새 connection과 API에서 보존을 확인하고, daily는 idempotent 전체 pipeline을 재실행해 rate-limit reset 경계와 pending bootstrap 복구를 확인한다.
- 2026-10-13: tracking의 신규 run과 동일 slot 재실행 경로에서 ranking publication 직후 outer transaction을 명시적으로 commit하도록 수정하고, 별도 DB connection에서 `published_at`이 보존되는 회귀 검증을 추가. GitHub rate-limit 응답은 reset epoch보다 1초 뒤이면서 exponential backoff보다 짧지 않게 대기하도록 수정해 reset 경계의 0초 재시도를 제거하고 resource/limit/reset/sleep을 구조화 로그에 추가했다. `TEST_DATABASE_URL=... uv run pytest`는 133 passed, GitHub live 1 skipped였고 `uv run ruff check ...`, `uv run mypy`도 통과했다. staging 배포와 Railway `Run now` 검증 전까지 Phase 13은 `[!]`를 유지한다.
- 2026-10-13: 수정 image를 staging의 tracking deployment `d60318f4-5170-4cea-90d9-56f7746c0da3`와 daily deployment `f746c1ab-ddc6-46e3-8635-39674bae5b4a`에 배포해 모두 `SUCCESS` 확인. Tracking `Run now`는 완료된 run 5를 재사용해 snapshot 재수집 없이 6초 만에 `EXITED`, 6,252 ranking을 공개했고 API가 `state=ready`, `tracking_run_id=5`, 7d 2,957건을 반환했다. Daily `Run now`는 16분 27초 만에 `EXITED`; discovery run 2가 4,616 discovered / 1,118 added / 실패 range 0으로 `COMPLETED`, bootstrap은 기존 pending 13건을 포함한 1,131건 모두 완료·실패 0, pipeline도 `COMPLETED`였다. `/ready` HTTP 200과 error-level log 0건을 확인해 Phase 13을 완료 처리한다.

## Phase 14 — MVP 통합 인수 검증

**목표:** PRD 10절 완료 기준을 production-like 환경에서 끝까지 검증한다.

**선행 조건:** Phase 13

**상태:** `[x]` — 2026-10-14 수정 배포 후 첫 고유 Railway staging tracking slot과 DB/API/web/log 인수 검증 완료

### 구현 항목

- [x] category sync → discovery → bootstrap → tracking → ranking publication → API 전체 흐름을 빈 DB integration fixture로 실행하고, frontend 회귀 suite로 UI 계약을 함께 검증한다.
- [x] 최소 24시간의 실제 snapshot이 필요한 24h ranking을 synthetic/integration fixture와 2026-10-14 06:00 UTC staging run에서 모두 검증했다.
- [x] staging에서 실제 snapshot 보존, 24h 실제 baseline 전환, identity mismatch 수정 배포 뒤 첫 고유 slot의 정상 종료를 확인했다.
- [x] release checklist, rollback 절차, known limitation을 `docs/MVP_RELEASE_CHECKLIST.md`와 운영 가이드에 문서화한다.
- [x] 현재 완료 항목과 실행 기록을 갱신한다.

### 완료 조건

- [x] 매일 topic discovery가 신규 repository를 중복 없이 저장한다.
- [x] 6시간 tracking이 snapshot을 수집하고 과거 snapshot을 보존한다.
- [x] 24h/7d/30d ranking, category filter, pagination이 동작한다.
- [x] 신규 repository가 7d/30d 추정 ranking에 참여하고 24h는 실제 history가 있을 때만 참여한다.
- [x] 95% 미만 수집 실패가 직전 공개 ranking을 유지한다.
- [x] 사용자가 ranking과 repository별 30일 star 추이를 웹에서 조회한다.
- [x] 로그인, 알림, LLM 분류 등 MVP 제외 기능이 포함되지 않는다.

### 테스트 방법

- [x] 전체 backend test, lint, type check를 실행한다.
- [x] 전체 frontend test, lint, type check, production build를 실행한다.
- [x] 빈 DB에서 migration과 seed 후 end-to-end flow를 실행한다.
- [x] duplicate discovery, search 분할/미완료, bootstrap, baseline, 동점/filter, partial failure, 95% 판정, rename/비활성화, API pagination 회귀 suite를 실행한다.
- [x] 실제/추정 graph 구분과 데이터 준비 중 상태를 component/UI acceptance regression으로 확인한다.

### 실행 기록

- 2026-10-13: `backend/tests/test_mvp_acceptance.py`를 추가. 빈 PostgreSQL schema에서 Alembic migration과 category sync 후, 21개 활성 topic discovery(반복 discovery의 `github_id` dedupe 포함), pending bootstrap, 첫 tracking publication, source-history refresh, 24시간 뒤 두 번째 tracking publication, FastAPI health/readiness/category/ranking/detail/history를 하나의 fixture로 검증했다. 24h는 실제 baseline, 7d/30d는 추정 baseline으로 구분됨을 확인했다.
- 2026-10-13: 통합 fixture에서 발견한 다음 날 bootstrap source-history 공백을 수정. daily pipeline이 `--refresh-active`로 tracking 시작 후 30일 이내 active repository의 누락 provider 날짜만 보존하며, 이전 원천 row와 현재 star 값은 덮어쓰지 않는다. 이로써 실제 24h snapshot과 유효한 7d/30d bootstrap ranking이 같은 run에서 유지된다.
- 2026-10-13: `docs/MVP_RELEASE_CHECKLIST.md`를 추가하고 운영 가이드에 refresh 동작을 반영. release 전/후 점검, rollback·incident 절차, Search 완전성·bootstrap 추정·24h history의 알려진 제한을 기록했다.
- 2026-10-13: `TEST_DATABASE_URL=... uv run pytest` — 134 passed, GitHub live 1 skipped. `uv run ruff check .`, `uv run mypy` — 통과. Linux Node 24.21.0으로 `npm --prefix frontend test` — 18 passed, `lint`, `typecheck`, `build` 및 `npm run iac:check`, `npm run iac:test` — 모두 통과.
- 2026-10-13: 빈 로컬 PostgreSQL public schema에서 `alembic upgrade head`, `repovil-sync-categories` 2회, `repovil-db-check`를 실행해 migration·seed idempotency와 DB 연결을 확인.
- 2026-10-13: refresh 변경 image를 Railway staging daily deployment `63b4c9f2-56cf-48f8-a774-7e151e6cb38d`에 배포하고 `Run now`를 실행. 17분 7초 뒤 `EXITED`했으며 discovery run 3은 4,623 discovered / 8 added / 실패 range 0으로 `COMPLETED`, bootstrap은 active 4,624개를 모두 refresh하고 실패 0, `daily_pipeline_finished=COMPLETED`였다. 새 DB 연결에서 bootstrap source history 137,752행 / 4,624 repository와 마지막 fetch `2026-10-13 10:01:33 UTC`를 확인했다.
- 2026-10-13: 같은 06:00 UTC slot에서 tracking `Run now`를 실행해 완료된 run 5를 재사용하고 `EXITED`함을 확인했다. 새 DB 연결에서 run 5의 `published_at`, snapshot 3,485건과 ranking 6,252건이 보존됐고 success-without-snapshot, non-success-with-snapshot, pending item이 모두 0이었다. API `/health`, `/ready`, 6개 category, 7d/30d ranking, category filter, pagination, repository detail/history와 web ranking 화면이 HTTP 200이었다. 24h는 아직 유효한 실제 baseline이 없어 ready 빈 결과이며, token/DB URL/authorization 로그 패턴 노출은 0건이었다.
- 2026-10-13: daily의 repository 단위 구조화 로그가 Railway의 replica 500 logs/sec 한도를 넘겨 일부 로그가 drop됐다. 작업 결과와 DB 무결성에는 영향이 없었지만 고빈도 성공 로그 축소는 후속 운영 개선으로 남긴다.
- 2026-10-14: Railway Cron Runs에서 tracking 2026-10-13 12:00/18:00 UTC가 각각 `EXITED`, DB run 8/9가 `COMPLETED`임을 확인. 2026-10-14 00:00/06:00 UTC는 동일 repository id 3848의 저장 `github_id`와 현재 owner/name 경로가 가리키는 `github_id` 불일치 1건 때문에 DB run 10/11이 `PARTIAL`, Railway는 non-zero exit 정책에 따라 `CRASHED`였다. 06:00 run 11은 4,629 success / 1 failed / 0 skipped, snapshot 4,629건과 ranking 9,909건을 원자적으로 공개했다.
- 2026-10-14: owner/name 재사용으로 다른 GitHub identity가 확인된 경우 저장 identity와 history를 보존하면서 원 repository를 inactive로 전환하고 `skipped`로 기록하도록 수정. 회귀 테스트를 추가했고 `TEST_DATABASE_URL=... uv run pytest`는 135 passed, GitHub live 1 skipped, `uv run ruff check .`, `uv run mypy`, `git diff --check`는 통과했다. tracking staging deployment `36245b69-4f9d-4c96-8de4-0e5753323101` 빌드와 후속 활성 deployment `fc1cf278-e27c-456e-a34d-0b97c13abebf`가 `SUCCESS`였다.
- 2026-10-14: scheduled daily 03:00 UTC Cron Run은 03:00:32~03:16:01 UTC `EXITED`; discovery run 4는 4,628 discovered / 19 added / 실패 range 0, bootstrap refresh 4,630 completed / 0 failed로 pipeline `COMPLETED`였다. 새 DB 연결에서 run 11의 success-without-snapshot, non-success-with-snapshot, orphan, pending이 모두 0이고, repository 4,623개가 snapshot 2개 이상, 4,610개가 4개 이상, 표본 repository는 5개 실제 snapshot을 보존함을 확인했다.
- 2026-10-14: run 11의 24h ranking 1,924건은 `is_estimated=true` 0건, 실제 baseline 누락 0건, `star_gain` 재계산 불일치 0건이었다. baseline은 모두 tracking run 5의 실제 snapshot이고 간격은 24.003~24.051시간이었다. API `/health`, `/ready`, category 6개, run 11의 24h 1,924건 / 7d 3,677건 / 30d 4,308건, `skills` filter 459건, page 2, repository detail/history와 web 24h 화면 HTTP 200을 확인했다. 조회한 daily/tracking 로그에서 token 실제값, DB URL 실제값, token/DB URL 패턴, Authorization/Bearer 노출은 모두 0건이었다.
- 2026-10-14: 수정 image의 활성 tracking deployment `fc1cf278-e27c-456e-a34d-0b97c13abebf`에서 첫 고유 12:00 UTC Cron Run이 12:03:35 UTC 환경 검증 후 시작해 12:37:13 UTC 최종 요약을 남기고 Railway instance `5e5f4fef-76e9-4dc2-942d-fe584d917f8b`가 `EXITED`했다. 새 DB 연결에서 run 12는 12:03:36~12:36:33 UTC `COMPLETED` 및 공개 완료였고, 4,630 대상 중 4,627 success / 0 failed / 3 skipped, snapshot 4,627건, ranking 9,874건(24h 1,892 / 7d 3,675 / 30d 4,307)이었다.
- 2026-10-14: run 12의 success-without-snapshot, non-success-with-snapshot, orphan snapshot, pending item은 모두 0이었다. 문제 repository id 3848은 원래 `github_id=642065600`, `Anil-matcha/awesome-jev-by-typesafe`와 run 8/9의 snapshot 2건을 보존하고, 다른 identity `1415634409`로의 owner/name 재사용을 `RepositoryIdentityMismatchError`로 기록하면서 run 12에서 `skipped`, repository는 `inactive`가 됐다. 나머지 skipped 2건은 GitHub 404로 비활성화된 repository였으며 failed item은 없었다.
- 2026-10-14: run 12의 24h ranking 1,892건은 모두 run 8의 실제 snapshot을 baseline으로 사용해 간격이 24.0000~24.0591시간이었고, `is_estimated=true`, baseline 누락, current star 및 `star_gain` 재계산 불일치는 모두 0이었다. API 95페이지 전체에서도 1,892개 고유 항목, `tracking_run_id=12`, estimated 0건을 확인했다.
- 2026-10-14: staging API `/health`, `/ready`, 24h/7d/30d ranking, `skills` category filter(24h 413건), 24h page 2, `deeplethe/solid-glass` 상세와 star-history가 모두 HTTP 200이었다. web 24h ranking 화면도 HTTP 200이며 해당 repository를 렌더링했다. tracking 실행 로그 13,891건을 30초 구간으로 나눠 누락 경고 없이 전수 검사해 error/warning/failure event 0건, skipped event 3건, 실제 GitHub token·DB URL과 변수명·`Authorization`·`Bearer`·token/URL 패턴 노출 모두 0건을 확인했다. 이로써 Phase 14와 MVP 통합 인수 검증을 완료한다.
- 2026-10-14: 완료 처리 직전 `TEST_DATABASE_URL=... uv run pytest` — 135 passed, GitHub live 1 skipped. `uv run ruff check .`, `uv run mypy`(32 source files), `git diff --check` — 모두 통과했다.

## Phase 15 — Production 배포 준비와 승인 게이트

**목표:** production에 resource를 생성하기 전에 배포 대상을 고정하고 secret, backup/PITR, IaC 변경 범위와 rollback 기준을 확정한다.

**선행 조건:** Phase 14

**상태:** `[x]` — 완료

### 범위 제한

- 이 Phase에서는 `railway config apply`, service 배포, domain 생성, worker 실행을 하지 않는다.
- production data를 만들거나 staging resource를 변경하지 않는다.
- custom domain, 로그량 최적화, 비용 최적화는 최초 배포의 필수 범위에 포함하지 않는다.

### 구현 항목

- [x] `main`과 `origin/main`이 일치하고 worktree가 깨끗한지 확인한 뒤 production release commit을 기록한다.
- [x] release commit 기준 backend 전체 test/ruff/mypy, frontend test/lint/typecheck/build, IaC typecheck/test와 `git diff --check` 결과를 기록한다. 코드 변경이 없다면 같은 commit에서 이미 실행한 결과를 재사용할 수 있다.
- [x] Railway target이 `production` environment인지 확인하고 현재 production resource와 variable **이름만** 조회한다. 값은 출력하거나 문서에 기록하지 않는다.
- [x] production용 최소 권한 `GITHUB_TOKEN`을 Railway shared variable로 준비한다. API/web에는 token이 없고 daily/tracking만 shared reference를 받는 구성을 확인한다.
- [x] PostgreSQL backup/PITR를 production에서 사용할 수 있는 plan과 활성화 절차를 확인한다. 사용할 수 없으면 Phase 16을 시작하지 않고 필요한 plan 변경 또는 승인된 대안을 사용자에게 요청한다.
- [x] `railway config plan`을 production 대상으로 실행해 Postgres, API, web, daily, tracking만 포함되는지 확인하고 add/change/destroy 수와 세부 대상을 기록한다.
- [x] 다음 cron slot 직후의 배포 시각, rollback에 사용할 직전 검증 image/commit, 실패 시 중단 조건을 정한다.
- [x] 검토된 plan과 production apply에 대해 사용자 승인을 받는다. plan이 바뀌면 기존 승인은 무효로 보고 다시 검토한다.

### 완료 조건

- [x] release commit과 전체 품질 gate가 통과 상태다.
- [x] production secret 경계와 backup/PITR 준비 방법이 확정됐다.
- [x] 예상하지 않은 resource 변경과 destroy가 없는 production plan이 기록됐다.
- [x] Phase 16의 정확한 apply 대상과 rollback 기준이 명확하며 사용자가 production 변경을 승인했다.

### 테스트 방법

- [x] `git status --short --branch`, release commit, 전체 release gate 결과를 확인한다.
- [x] production variable 이름과 IaC reference를 대조하되 secret 값은 어느 출력에도 남기지 않는다.
- [x] `npm run iac:check`, `npm run iac:test`를 실행한다.
- [x] production `railway config plan`을 읽기 전용으로 실행하고 environment, add/change/destroy 및 대상 resource를 수동 검토한다.

### 실행 기록

- 2026-10-14: 시작 시 `main`과 `origin/main`은 `5b44cdd71cba76184f7e01baf963c3b688004ccf`로 일치했고 worktree는 깨끗했다. production application release commit은 마지막 application 변경인 `a766030036f02e405dc93f5a155340659e8b3bf4`이며, 이후 `a6b102c`와 `5b44cdd`는 구현 계획 문서만 변경했다. Phase 15 기록을 사용자가 commit한 뒤 Phase 16 시작 직전에 다시 `main == origin/main`과 application/IaC 무변경을 확인한다.
- 2026-10-14: application 내용이 같은 `a6b102c` 기준 release gate를 재사용했다. backend는 135 passed / GitHub live 1 skipped, Ruff 통과, mypy 32 source files 통과였다. frontend는 18 passed, lint/typecheck/build가 통과했고 IaC는 typecheck와 3 tests, `git diff --check`가 통과했다. Phase 15에서 IaC typecheck와 3 tests, `git diff --check`를 다시 실행해 모두 통과했다.
- 2026-10-14: Railway project `Repovil`의 production environment는 `76f2d1f0-cb43-46c1-939c-8f2cf04fdb8d`이며 resource가 0개였다. 최초 Public API의 active shared-variable query 결과 variable 이름도 0개였고 값은 조회 결과에 출력하지 않았다. IaC는 API/web에 token을 전달하지 않고 `repovil-daily`와 `repovil-tracking`의 `GITHUB_TOKEN`만 `${{shared.GITHUB_TOKEN}}`을 참조하며, 이 경계는 IaC test로 확인했다.
- 2026-10-14: 최초 확인 당시 project의 `subscriptionType`은 `trial`이었다. Railway의 [volume backup](https://docs.railway.com/volumes/backups), [Postgres PITR](https://docs.railway.com/volumes/point-in-time-recovery) 공식 문서와 CLI 5.68.0에서 scheduled backup과 PITR를 확인했으며 PITR 자체에는 별도 기능 요금이 없고 bucket storage와 upload egress가 과금된다. production Postgres가 아직 없어 현재 PITR status는 `enabled=false`, `bucketWired=false`이고 database image가 없다는 blocker를 반환하는 것이 정상이다. Phase 16에서는 Postgres 첫 배포 성공 직후 worker 실행 전에 production service ID를 다시 확인하고 `railway postgres pitr enable --service ID --environment production`, `railway postgres pitr schedule set --daily --weekly --monthly --service ID --environment production`을 실행한다. 이어 `pitr status`에서 enabled/bucket wiring/blocker와 최초 backup coverage를, `pitr schedule list`에서 세 schedule을 확인한다. 하나라도 확인되지 않으면 worker를 실행하지 않는다.
- 2026-10-14: Linux Node를 지정한 읽기 전용 `railway config plan --environment production --verbose` 결과는 정확히 5 add / 0 change / 0 destroy였다. add 대상은 `Postgres`, `repovil-api`, `repovil-web`, `repovil-daily`, `repovil-tracking`뿐이며 production apply, service 배포, domain 생성, worker 실행 및 staging 변경은 수행하지 않았다.
- 2026-10-14: 승인 후 첫 배포 창은 다음 `0 */6 * * *` tracking slot의 5~15분 뒤로 정했다. 현재 시각 기준 후보는 2026-10-14 18:05~18:15 UTC(2026-10-15 03:05~03:15 KST)이며 놓치면 다음 00/06/12/18 UTC slot 뒤 같은 창으로 이동한다. application rollback 기준은 staging에서 검증된 `a766030`이고, 특히 최종 tracking image는 deployment `fc1cf278-e27c-456e-a34d-0b97c13abebf` / digest `sha256:127e0cbd21a04a941d0f4468afffb1daf8ba03c4192a550c5bce5b0b437e342c`다. 최초 production에는 직전 image가 없으므로 실패 시 domain/worker를 진행하지 않고 DB와 실행 이력을 보존한 채 중단하며, schema downgrade나 restore는 별도 승인 없이 하지 않는다. 첫 성공 production deployment ID/image는 즉시 이후 rollback 대상으로 기록한다.
- 2026-10-14: 사용자가 workspace를 Hobby plan으로 전환했다. Public API에서 `subscriptionType=hobby`를 확인했고, 사용자는 5 add / 0 change / 0 destroy plan, PITR/backup storage·egress 비용 및 Phase 16 production apply를 명시적으로 승인했다. 승인 후 production plan을 다시 실행해 대상과 수치가 바뀌지 않았음을 확인했다.
- 2026-10-14: production environment staged patch `2a924aa6-f36b-4288-8c9d-21333dc3c479`가 `STAGED`이고 `patch.sharedVariables.GITHUB_TOKEN`을 포함함을 `decryptVariables=false`로 확인했다. 실제 token 값은 조회하거나 출력하지 않았다. 서비스가 아직 없어 active shared-variable 목록이 빈 것은 정상이며, Phase 16 apply 직전 이 patch와 token reference가 유지되는지 다시 확인한다. Apply 후 active shared-variable 이름과 daily/tracking reference를 확인하고 API/web에는 token이 없는지 검증하며, 하나라도 다르면 worker 실행 전에 중단한다. 이로써 Phase 15를 완료하며 production apply와 Phase 16 실행은 아직 수행하지 않았다.

## Phase 16 — Production 배포와 초기 운영 검증

**목표:** 승인된 IaC plan을 production에 적용하고 초기 데이터 pipeline과 공개 API/web이 정상인 상태로 MVP 배포를 완료한다.

**선행 조건:** Phase 15

**상태:** `[x]` — 2026-10-15 완료 (승인된 Hobby PITR-only / Pro backup schedule 예외 적용)

### 범위 제한

- Phase 15에서 승인된 plan만 적용한다. apply 직전 plan이 달라지면 즉시 중단하고 재승인을 받는다.
- Railway 생성 domain을 사용하며 custom domain/DNS 설정은 최초 배포 완료 조건에서 제외한다.
- staging data를 production으로 복사하지 않고 production pipeline이 자체 데이터를 생성하게 한다.
- production 24h ranking은 실제 snapshot이 24시간 이상 쌓인 뒤 생기는 것이 정상이며, 그 대기 자체는 이 Phase의 완료를 막지 않는다.

### 구현 항목

- [x] 다음 cron slot 직후에 production plan을 다시 확인하고 승인된 내용과 같을 때만 `railway config apply`를 실행한다.
- [x] Postgres와 API/web/daily/tracking service가 생성되고 API pre-deploy의 환경 검사, Alembic upgrade, category sync 및 각 deployment가 성공했는지 확인한다.
- [x] production PostgreSQL의 backup/PITR가 초기 pipeline 실행 전에 실제로 활성화됐는지 확인한다.
- [x] API와 web의 Railway production domain을 생성하고 `/health`, `/ready`, web `/`, `/categories`가 HTTP 200이며 활성 category 6개를 반환하는지 확인한다.
- [x] daily worker를 한 번 실행해 discovery와 bootstrap이 `COMPLETED`, failed range와 bootstrap failure가 0인지 확인한다. 실패하면 원인을 해결한 뒤 기록된 실패 범위/대상만 안전하게 재시도한다.
- [x] daily 완료 후 tracking worker를 한 번 실행해 Railway가 `EXITED`, DB run이 `COMPLETED`이고 ranking이 공개됐는지 새 DB connection으로 확인한다.
- [x] tracking run의 success/failed/skipped/pending, snapshot/ranking 수와 success-without-snapshot, non-success-with-snapshot, orphan snapshot, pending item 무결성을 확인한다.
- [x] API의 7d/30d ranking, category filter, pagination, repository detail, star-history와 web ranking 화면을 검증한다. 24h는 HTTP 200과 준비 상태 또는 실제 history에 맞는 결과만 요구한다.
- [x] production worker 로그에서 failure event를 확인하고 GitHub token, DB URL, `Authorization`/`Bearer` 및 secret 패턴 노출이 0인지 검사한다.
- [x] daily `0 3 * * *`, tracking `0 */6 * * *` UTC와 다음 cron 시각이 설정됐는지 확인하고 deployment/run/domain/수치/로그 결과를 이 문서에 기록한다.

### 완료 조건

- [x] production API/web이 public domain에서 healthy/ready 상태다.
- [x] production daily와 tracking 초기 실행이 성공하고 새 DB connection에서도 snapshot, ranking, publication이 보존된다.
- [x] API/web의 MVP 주요 경로가 production data로 동작한다.
- [x] DB 무결성 오류와 secret 로그 노출이 모두 0이다.
- [x] UTC cron 설정, backup/PITR, rollback 대상과 장애 대응 경로가 확인됐다.

### 테스트 방법

- [x] Railway plan/apply 및 API pre-deploy/build/deployment 로그를 확인한다.
- [x] `/health`, `/ready`, `/categories`, `/rankings`, repository detail/history와 web `/`를 실제 production domain에서 요청한다.
- [x] 새 production DB connection으로 run, item, snapshot, ranking, publication 및 네 무결성 query를 실행한다.
- [x] daily/tracking 전체 로그를 secret 실제값과 안전한 패턴으로 대조하고 failure event를 집계한다.
- [x] `railway status`에서 service 상태, cron schedule과 다음 실행 시각을 확인한다.

### 중단 및 rollback 기준

- apply 전 environment 또는 plan이 Phase 15 승인 내용과 다르면 변경하지 않고 중단한다.
- migration/category sync, backup/PITR, health/readiness 또는 필수 variable 검증이 실패하면 worker를 실행하지 않고 원인을 해결한다.
- worker가 실패하면 실패 run을 성공처럼 수정하지 않고 `docs/RAILWAY_OPERATIONS.md`의 targeted retry 절차를 따른다.
- application rollback은 schema와 호환되는 검증 image만 redeploy한다. production DB downgrade나 data restore는 별도 명시적 승인 없이는 실행하지 않는다.

### 실행 기록

- 2026-10-15: 00:00 UTC tracking slot 직후 `main == origin/main == 166eeca21f246dd1dc8f3b054fe1376ae9f57385`와 검증된 application/IaC 내용이 유지됨을 확인했다. Linux Node 24.21.0으로 IaC typecheck와 graph test 3개가 통과했다.
- 2026-10-15: apply 직전 production environment `76f2d1f0-cb43-46c1-939c-8f2cf04fdb8d`가 빈 상태임을 확인하고, pinned plan을 다시 생성했다. 결과는 승인 내용과 정확히 같은 5 add / 0 change / 0 destroy였고 대상은 `Postgres`, `repovil-api`, `repovil-web`, `repovil-daily`, `repovil-tracking`뿐이었다. 해당 pinned plan을 production에 적용했다.
- 2026-10-15: Postgres service와 volume이 `SUCCESS`/`RUNNING`/`READY`가 된 뒤 PITR를 활성화해 `enabled=true`, `bucketWired=true`를 확인했다. 그러나 daily/weekly/monthly backup schedule 설정은 Railway가 `Manual backups and backup schedules are only available for Pro workspaces`로 거부했고 schedule 목록은 비어 있었다. Hobby에서 승인된 backup 절차를 완료할 수 없어 worker 수동 실행을 중단했다.
- 2026-10-15: apply된 변수 이름과 값 존재 여부만 검사했다. API/web에는 `GITHUB_TOKEN`이 없고 daily/tracking에만 non-empty token과 API version이 있으며 DB/API private reference도 존재해 secret 경계는 계획과 일치했다. Postgres, web, daily, tracking deployment는 성공했지만 API deployment `1b95b88d-cc19-4d56-9993-254876178bdd`의 pre-deploy Alembic 단계가 실패했다.
- 2026-10-15: API 실패를 값 노출 없이 진단한 결과 production `PGPASSWORD`가 실제 난수가 아니라 미평가된 `secret(...)` 호출 문자열이며 `DATABASE_URL`도 같은 값을 포함해 Pydantic URL 검증에서 `invalid port number`로 거부됐다. staging password는 32자 영숫자 난수로 정상이다. production credential rotation과 URL 복구가 필요하다. domain 생성, health/API smoke, daily/tracking 수동 실행은 수행하지 않았으며 production data row는 아직 만들지 않았다.
- 2026-10-15: production PostgreSQL credential을 실제 값 출력 없이 rotation하고 reference를 복구했다. API deployment `872beff8-d562-4cb5-b2c7-ad1b0d87eb3b`가 `SUCCESS`였으며 pre-deploy 로그에서 Alembic `20261011_0001`/`20261011_0002` upgrade와 6 categories / 21 topics / 21 active mappings sync를 확인했다. Postgres/API/web/daily/tracking 최신 deployment는 모두 `SUCCESS`이고 API/web 생성 domain은 각각 `https://repovil-api-production.up.railway.app`, `https://repovil-web-production.up.railway.app`이다.
- 2026-10-15: Hobby plan 제약에 따라 사용자가 PITR-only와 scheduled backup이 Pro 전용인 예외를 승인했다. 최종 PITR 상태는 enabled, bucket wired, archiver enabled, backup set 1개이며 `2026-10-15 07:11:53 UTC`까지 live restore coverage를 확인했다. 별도 daily/weekly/monthly backup schedule은 승인된 예외대로 없다.
- 2026-10-15: 수동 daily Cron Run `3f389b05-9b6b-4dbc-8cba-d032bc782543`는 `EXITED`; discovery run 1은 4,647 discovered / 4,647 added / failed range 0으로 `COMPLETED`, bootstrap은 4,647 completed / 0 failed였다. 이어 03:00 UTC scheduled daily Cron Run `a61a7af0-7935-4db8-a46f-d94b09df1412`도 `EXITED`; discovery run 2는 4,650 discovered / 3 added / failed range 0으로 `COMPLETED`, bootstrap은 4,650 completed / 0 failed였다. 새 DB 연결에서 active 4,649 / inactive 1 / bootstrap pending 0, bootstrap 원천 138,530행 / 4,650 repository를 확인했다.
- 2026-10-15: 06:00 UTC scheduled tracking Cron Run `3dfd34a4-6f1a-4507-a59c-5af2623d10e4`를 중복 실행 없이 관찰했다. GitHub rate-limit reset 대기 후 Railway는 `EXITED`, DB run 1은 `COMPLETED`/published가 됐고 4,650 대상 중 4,649 success / 0 failed / 1 skipped / 0 pending, snapshot 4,649건, ranking 8,116건(7d 3,772 / 30d 4,344)이 보존됐다. 첫 실측 snapshot만 존재해 24h ranking 0건인 것은 PRD와 일치한다.
- 2026-10-15: run 1의 success-without-snapshot, non-success-with-snapshot, orphan snapshot, pending item은 모두 0이었다. 모든 7d/30d ranking은 첫 run 특성상 bootstrap 추정치이고 `star_gain <= 0` row는 0건이었다.
- 2026-10-15: production API `/health`, `/ready`, `/categories`(활성 6개), 24h/7d/30d ranking, `skills` category filter(7d 660건), page 2, repository detail와 star-history가 모두 HTTP 200이었다. 24h는 ready/0건, 7d는 3,772건, 30d는 4,344건으로 DB와 일치했고 page 1/2 중복은 0이었다. 표본 history는 actual 1점 / estimated 11점이었으며 web 7d ranking도 HTTP 200으로 API 최상위 repository를 렌더링했다.
- 2026-10-15: scheduled daily 로그 14,157줄과 tracking 로그 13,955줄을 1분 이하 구간으로 나눠 상한 누락 없이 검사했다. failure event, 실제 GitHub token/DB credential 값, `GITHUB_TOKEN`/`DATABASE_URL`, `Authorization`/`Bearer`, token/DB URL 패턴, 로그 drop 경고는 모두 0건이었다.
- 2026-10-15: cron은 daily `0 3 * * *`(다음 `2026-10-16 03:00 UTC`), tracking `0 */6 * * *`(다음 `2026-10-15 12:00 UTC`)로 확인했다. production API/web/Postgres는 `RUNNING`, daily/tracking은 성공 종료 후 `EXITED`였다. 검증 완료 후 Railway SSH key `repovil-phase16-temporary`, `repovil-phase16-temporary-recovery`와 추가 최종 검증 key를 모두 제거해 등록 key 0개를 확인했고 `/tmp/repovil-phase16.FANWiS`도 제거했다. 이로써 승인된 예외를 포함한 Phase 16 production 검증을 완료한다.

## 5. PRD 요구사항 추적표

| PRD MVP 완료 기준 | 담당 Phase | 핵심 검증 |
|---|---:|---|
| Topic 기반 일일 발견과 중복 없는 저장 | 3, 6 | YAML 일치, `github_id` upsert, search 분할/실패 구간 |
| 6시간 snapshot 수집·보존 | 4, 8 | run target 고정, unique snapshot, stale 대체 금지 |
| 24h/7d/30d ranking과 category filter | 9, 10, 11 | baseline 허용 오차, 정렬, join 중복 제거, UI filter |
| 7d/30d bootstrap 및 24h 실측 전용 | 7, 9, 12 | invalid 추정 제외, `is_estimated`, 실제값 우선 |
| 일부 실패 시 공개 ranking 보호 | 8, 9, 13 | 성공률 95%, atomic publish, 직전 run 유지 |
| 웹 ranking과 repository star 추이 | 10, 11, 12 | read-only API, 20개 pagination, 30일 graph |

## 6. MVP 종료 후에만 재검토할 항목

다음 항목은 현재 계획에 포함하지 않는다.

- GraphQL을 이용한 tracking 최적화
- webhook 또는 event-driven 수집
- LLM 기반 category 검증
- 사용자 계정, 저장, 알림, 비교, 추천
- snapshot downsampling 또는 장기 archive
- 관리자 UI, 운영 분석 dashboard
- Redis/queue 도입이나 worker 수평 확장을 위한 범용 orchestration

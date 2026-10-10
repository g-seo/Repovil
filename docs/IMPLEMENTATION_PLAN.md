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

`Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14`

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

### 구현 항목

- [ ] 검증 일자, 사용한 REST API version, 인증 방식, test repository/topic, 요청/응답 요약을 `docs/GITHUB_API_VALIDATION.md`에 기록한다. token과 개인 정보는 기록하지 않는다.
- [ ] `GET /search/repositories`가 `topic`, `stars`, public/non-fork/non-archived 조건과 정렬·pagination을 실제로 지원하는지 확인한다.
- [ ] Search가 반환하는 `total_count`, `incomplete_results`, 최대 1,000개 접근 제한, `per_page`/page 한계를 확인한다.
- [ ] star 범위의 양 끝이 포함되는지 확인하고, 인접 구간 중복 방지 규칙을 정한다.
- [ ] 결과가 1,000개를 넘는 구간을 재귀 분할할 수 있는지 표본 topic으로 검증한다. 단일 star 값 구간도 1,000개를 넘으면 해당 구간을 실패로 기록해야 하며, PRD 승인 없이 다른 발견 방식을 추가하지 않는다.
- [ ] repository 조회에서 `github_id`, owner/name, topics, visibility, fork, archived, current star 수를 얻을 수 있는지와 rename redirect, 404 동작을 확인한다.
- [ ] `GET /repos/{owner}/{repo}/stargazers/count`와 `GET /repos/{owner}/{repo}/stargazers/history`의 가용성, public repository 권한, 응답 형식, pagination을 live 요청으로 확인한다.
- [ ] star history의 주별 묶음, 일별 `stars_created`, 최신순 page, UTC와 일치하지 않을 수 있는 경계, 최대 `per_page=30`/`page=100` 제약을 확인한다.
- [ ] star history가 생성된 star 수이며 unstar를 복원하지 못한다는 점을 fixture 기대값에 반영한다.
- [ ] 인증/비인증 primary rate limit, Search 전용 limit, `x-ratelimit-*`, `Retry-After`, 403/429 및 secondary limit 처리 규칙을 확인한다.
- [ ] 예상 repository 수를 표본 검색으로 산정하고 daily discovery, 신규 bootstrap, 6시간 tracking의 요청 예산이 운영 가능한지 계산한다.
- [ ] PRD의 `GitHubClient` 메서드 각각을 검증된 REST endpoint에 매핑한다. REST로 구현하며 GraphQL 전환은 MVP에서 제외한다.

### 완료 조건

- [ ] Search 분할, metadata/status 조회, current star count, 30일 bootstrap에 필요한 데이터를 실제 API로 획득한 증거가 문서화된다.
- [ ] endpoint별 권한·pagination·rate limit·실패 의미와 API version pinning 정책이 확정된다.
- [ ] 요청 예산이 daily/6-hour schedule 안에서 가능한지 수치로 판단된다.
- [ ] 실제 API가 PRD를 지원하지 않으면 Phase 2로 진행하지 않고 `[!]`로 표시한 뒤 PRD 변경 여부를 사용자에게 요청한다. scraping이나 비공식 API를 임의로 도입하지 않는다.

### 테스트 방법

- [ ] 인증된 read-only token으로 소형·중형·대형 public repository에 read-only smoke request를 실행한다.
- [ ] 1,000건 이하/초과 search query, 마지막 page, `incomplete_results`를 검증한다.
- [ ] rate-limit response header와 404/422/403 또는 429 fixture를 보존 가능한 형태로 정리한다.
- [ ] GitHub 공식 문서와 live 결과의 차이를 기록한다.

### 공식 문서 기준선

- [Repository Search REST API](https://docs.github.com/en/rest/search/search)
- [Starring REST API](https://docs.github.com/en/rest/activity/starring)
- [REST API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)

### 실행 기록

- 미실행. 계획 작성 시 공식 문서만 검토했으며 live API 검증은 수행하지 않음.

## Phase 2 — 프로젝트 골격과 개발 품질 기준

**목표:** FastAPI/worker와 Next.js가 분리된 최소 실행 골격과 반복 가능한 개발 환경을 만든다.

**선행 조건:** Phase 1 통과

### 구현 항목

- [ ] `uv` 기반 Python package, FastAPI app, worker entry point, test directory를 구성한다.
- [ ] Next.js + TypeScript app을 구성한다.
- [ ] PostgreSQL만 포함한 local Docker Compose를 구성한다.
- [ ] 환경 변수 설정과 `.env.example`을 추가하되 실제 secret은 추가하지 않는다.
- [ ] backend에 pytest, lint, type check를 위한 최소 dev dependency와 명령을 구성한다.
- [ ] frontend에 test, lint, type check, build 명령을 구성한다. UI 단위 테스트에 필요한 최소 도구만 도입한다.
- [ ] API 코드와 worker 코드의 entry point를 분리하되 동일 backend package와 domain code를 공유하게 한다.

### 완료 조건

- [ ] 빈 FastAPI app과 Next.js app이 로컬에서 시작된다.
- [ ] PostgreSQL 연결 설정을 환경 변수로 주입할 수 있다.
- [ ] frontend/backend 품질 명령이 CI와 로컬에서 동일하게 실행 가능하다.
- [ ] Redis, task queue, 범용 repository/service framework 등 불필요한 구성요소가 없다.

### 테스트 방법

- [ ] backend unit test와 lint/type check를 실행한다.
- [ ] frontend test, lint, type check, production build를 실행한다.
- [ ] Docker Compose로 PostgreSQL을 시작하고 연결 smoke test를 실행한다.

### 실행 기록

- 미실행

## Phase 3 — Topic YAML 분리와 설정 검증

**목표:** PRD 3.1의 초기 Topic 매핑을 외부 설정으로 분리하고 안전하게 읽는다.

**선행 조건:** Phase 2

### 구현 항목

- [ ] PRD 3.1의 YAML을 내용 변경 없이 `config/categories.yaml`에 저장한다.
- [ ] `All`을 YAML category나 topic으로 추가하지 않는다.
- [ ] category의 `name`, `slug`, `active`, `display_order`, `topics`를 검증하는 단순 loader를 구현한다.
- [ ] 중복 category name/slug/display order, 중복 topic, 빈 topic 목록, 잘못된 slug를 명확한 오류로 거부한다.
- [ ] YAML을 DB로 idempotent seed/sync하는 명령의 계약을 정하고 Phase 0에서 확정한 제거 정책을 적용한다.

### 완료 조건

- [ ] 여섯 category와 모든 topic이 PRD와 동일하다.
- [ ] 설정 오류가 부분 반영 없이 시작/명령 단계에서 실패한다.
- [ ] 같은 설정을 반복 적용해도 중복 데이터가 생기지 않는다.

### 테스트 방법

- [ ] 정상 YAML parsing 및 PRD 기대값 snapshot test를 실행한다.
- [ ] 중복/누락/형식 오류 fixture에 대한 실패 테스트를 실행한다.
- [ ] `All`이 설정 결과에 존재하지 않는지 확인한다.

### 실행 기록

- 미실행

## Phase 4 — PostgreSQL schema와 Alembic migration

**목표:** PRD의 식별자, 이력 보존, run 단위 처리와 원자적 공개를 지원하는 최소 schema를 만든다.

**선행 조건:** Phase 3

### 구현 항목

- [ ] PRD 핵심 테이블 `repositories`, `topics`, `categories`, `category_topics`, `repository_topics`를 migration으로 만든다.
- [ ] `discovery_runs`, `tracking_runs`, `star_snapshots`, `bootstrap_star_history`, `rankings`를 migration으로 만든다.
- [ ] tracking 시작 시 대상 확정과 repository별 success/failed/skipped 기록을 위한 최소 run-item 테이블을 추가한다. `(tracking_run_id, repository_id)`를 unique하게 한다.
- [ ] `github_id UNIQUE`, run/repository 및 bootstrap 복합 key, ranking 복합 PK, `scheduled_at UNIQUE`를 구현한다.
- [ ] `star_snapshots(repository_id, captured_at DESC)`와 읽기 endpoint에 필요한 최소 index를 추가한다.
- [ ] timestamp는 timezone-aware PostgreSQL type으로 저장하고 애플리케이션 경계에서 UTC를 강제한다.
- [ ] star count와 run count가 음수가 되지 않도록 제약하고 period/status 값은 PRD 값만 허용한다.
- [ ] discovery 실패 구간을 재시도 가능한 구조로 저장한다. MVP에는 JSONB 또는 단순 child table 중 실제 query에 필요한 더 단순한 방식을 선택한다.
- [ ] Phase 3의 category seed/sync를 transaction으로 DB에 적용한다.

### 완료 조건

- [ ] 빈 PostgreSQL DB에 migration을 적용하면 PRD 데이터 모델과 제약이 생성된다.
- [ ] repository rename/transfer가 owner/name 변경일 뿐 `github_id` identity를 바꾸지 않는다.
- [ ] snapshot과 bootstrap 원천 row를 update/delete하지 않고 새 run을 누적할 수 있다.
- [ ] run 대상, 결과, 공개 여부를 DB만으로 감사할 수 있다.

### 테스트 방법

- [ ] 빈 DB에 `alembic upgrade head`를 실행한다.
- [ ] downgrade 후 다시 upgrade하는 migration smoke test를 실행한다.
- [ ] unique/FK/check constraint와 UTC round-trip integration test를 실행한다.
- [ ] category seed/sync를 두 번 실행해 idempotency를 확인한다.

### 실행 기록

- 미실행

## Phase 5 — GitHubClient REST adapter

**목표:** Phase 1에서 검증한 GitHub REST API만 캡슐화하고 worker가 일관되게 오류와 rate limit을 처리하게 한다.

**선행 조건:** Phase 4

### 구현 항목

- [ ] `search_repositories`, `get_repository`, `get_repository_stats`, `get_star_history`를 가진 최소 `GitHubClient`를 구현한다.
- [ ] API version, auth header, timeout, user agent와 response parsing을 한 곳에서 관리한다.
- [ ] pagination을 endpoint별 한계 안에서 구현한다.
- [ ] timeout, connection error, 5xx, retry 가능한 403/429에 bounded exponential backoff를 적용한다.
- [ ] 4xx를 not-found/자격 상태/인증 오류/rate limit/validation 오류로 구분하고 무한 재시도하지 않는다.
- [ ] `Retry-After`와 `x-ratelimit-reset`을 우선하며, request별 rate-limit metadata를 worker가 기록할 수 있게 한다.
- [ ] 구조화 로그 필드에 response status, retry count, duration을 제공하고 token은 redaction한다.
- [ ] API/FastAPI request path에서 이 client를 import하거나 호출하지 못하도록 package 경계와 테스트를 둔다.

### 완료 조건

- [ ] 모든 GitHub 호출이 `GitHubClient`를 통한다.
- [ ] client는 DB나 ranking 정책을 알지 못한다.
- [ ] 실패가 typed result/exception으로 worker에 전달되어 run 판정에 사용할 수 있다.
- [ ] Phase 1 fixture로 응답 parsing이 재현된다.

### 테스트 방법

- [ ] pagination, timeout, retry/backoff, 404, 422, 403/429, 5xx unit test를 실행한다.
- [ ] rate-limit header와 `Retry-After` 우선순위 테스트를 실행한다.
- [ ] API layer가 GitHubClient를 호출하지 않는 architecture test를 실행한다.
- [ ] opt-in live smoke test로 Phase 1 endpoint를 다시 확인한다.

### 실행 기록

- 미실행

## Phase 6 — Discovery worker

**목표:** 설정 topic별 repository를 매일 발견하고, 완전하지 않은 검색을 성공으로 숨기지 않으며, `github_id` 기준으로 저장한다.

**선행 조건:** Phase 5

### 구현 항목

- [ ] 활성 topic 각각에 대해 public, non-fork, non-archived, stars 200 이상 Search를 실행한다.
- [ ] 1,000건 초과 star 구간을 재귀 분할하고, 경계 중복은 `github_id`로 제거한다.
- [ ] `incomplete_results`, pagination/search 실패, rate limit, 더 분할할 수 없는 과다 구간을 실패 구간으로 저장한다.
- [ ] 실패 구간만 안전하게 재시도할 수 있게 하고, 미완료 run을 정상 완료로 표시하지 않는다.
- [ ] 결과를 다시 eligibility 검증한 뒤 신규 repository를 저장하고 기존 metadata와 topic을 갱신한다.
- [ ] 같은 repository가 여러 topic/category에 속하는 것을 보존한다.
- [ ] `github_id` 기준 upsert로 rename/transfer 시 owner/name/url을 갱신한다.
- [ ] 신규 eligible repository는 bootstrap 대기 상태로 저장하고 Phase 7 성공 후 tracking 대상으로 활성화한다.
- [ ] discovery job 중복 실행을 PostgreSQL lock/run 상태로 방지한다.
- [ ] run별 시작/종료, 발견 수, 추가 수, 상태, 실패 구간을 구조화 로그와 DB에 기록한다.

### 완료 조건

- [ ] 같은 결과를 반복 처리해도 repository와 관계가 중복되지 않는다.
- [ ] 일부 topic/구간 실패가 성공으로 기록되지 않고 재실행 가능하다.
- [ ] stars 200 미만 repository는 최초 저장되지 않는다.
- [ ] multi-category repository가 한 repository row와 여러 topic 관계로 저장된다.

### 테스트 방법

- [ ] 중복 discovery와 여러 topic 중복 결과 테스트를 실행한다.
- [ ] 999/1,000/1,001건 구간, inclusive boundary, 단일 star 과다 구간 테스트를 실행한다.
- [ ] `incomplete_results`, 중간 page 실패, rate limit 후 재시도 테스트를 실행한다.
- [ ] 신규/기존/rename/transfer metadata update integration test를 실행한다.
- [ ] 동시 실행 시 하나만 진행되는 DB lock test를 실행한다.

### 실행 기록

- 미실행

## Phase 7 — Historical bootstrap

**목표:** 신규 repository의 7d/30d ranking과 30일 graph에 사용할 추정 원천 데이터를 수집·보존한다.

**선행 조건:** Phase 6

### 구현 항목

- [ ] 신규 eligible repository에 대해 `get_star_history`를 호출해 필요한 최근 구간의 일별 `stars_created`를 저장한다.
- [ ] `(repository_id, date)` 기준 idempotent upsert와 `fetched_at` 기록을 구현한다.
- [ ] 최신 실측 star count에서 일별 생성 수를 역산해 7d/30d baseline 후보를 계산한다.
- [ ] API의 일 경계가 UTC와 정확히 일치하지 않음을 유지하고 결과를 항상 `is_estimated=true`로 표시할 수 있게 한다.
- [ ] unstar를 복원하지 못하는 추정치임을 domain model과 API contract에 반영한다.
- [ ] 음수 baseline, 누락/불연속 응답 등 유효하지 않은 추정치는 사용하지 않는다.
- [ ] bootstrap은 24h baseline에 절대 사용하지 않는다.
- [ ] bootstrap 성공 후 tracking을 활성화한다. 실패는 원인과 재시도 상태를 남기고 snapshot/ranking으로 위장하지 않는다.

### 완료 조건

- [ ] 유효한 신규 repository가 7d/30d 추정 baseline 후보를 갖는다.
- [ ] 원천 일별 데이터와 계산 결과를 분리해 재계산할 수 있다.
- [ ] 자체 snapshot이 충분해지면 ranking이 자동으로 실제 baseline을 우선할 수 있다.
- [ ] 잘못된 추정치가 ranking이나 graph에 포함되지 않는다.

### 테스트 방법

- [ ] known daily counts에서 7d/30d baseline 역산 테스트를 실행한다.
- [ ] unstar로 최신 count와 누적 생성 수가 어긋나는 fixture를 테스트한다.
- [ ] 음수, 누락, page 경계, 중복 fetch, API 실패 테스트를 실행한다.
- [ ] 24h 계산 경로가 bootstrap을 참조하지 않는 테스트를 실행한다.

### 실행 기록

- 미실행

## Phase 8 — Tracking 및 snapshot worker

**목표:** 6시간마다 대상 집합을 고정하고 성공한 실제 측정만 snapshot으로 보존한다.

**선행 조건:** Phase 7

### 구현 항목

- [ ] UTC schedule slot을 `scheduled_at`으로 사용해 idempotent `tracking_run`을 만들고 PostgreSQL 기반 중복 실행 방지를 적용한다.
- [ ] run 시작 시 활성 tracking 대상 전체를 run-item으로 확정한다.
- [ ] 각 대상의 current star 수, metadata, topics와 eligibility를 GitHubClient로 확인한다.
- [ ] 실제 응답 측정 시각을 `captured_at`으로 저장하고 scheduler 예정 시각으로 대체하지 않는다.
- [ ] 성공한 repository만 해당 run snapshot을 저장한다.
- [ ] transient 실패는 failed로 기록하고 이전 snapshot을 현재 run의 값으로 복사하지 않는다.
- [ ] stars 200 미만, archived, private, deleted, 모든 설정 topic 이탈을 확인하면 기록은 유지한 채 tracking/publication에서 비활성화한다.
- [ ] 비활성 repository가 이후 discovery에서 자격을 다시 만족하면 재활성화한다.
- [ ] repository별 success/failed/skipped와 오류, retry count, duration을 기록한다.
- [ ] `COMPLETED`, `PARTIAL`, `FAILED`를 PRD 정의대로 계산한다. publication은 다음 Phase에서 별도로 판정한다.

### 완료 조건

- [ ] 같은 schedule slot 재실행이 중복 run/snapshot을 만들지 않는다.
- [ ] target 목록은 run 도중 discovery 변경의 영향을 받지 않는다.
- [ ] 실패 대상에 stale snapshot이 생성되지 않는다.
- [ ] rename과 자격 상실/재활성화가 history를 잃지 않고 `github_id` 동일성을 유지한다.

### 테스트 방법

- [ ] 전체 성공, 일부 실패, 전부 실패, 분모 0 run 테스트를 실행한다.
- [ ] timeout/retry exhaustion 시 stale snapshot 미생성 테스트를 실행한다.
- [ ] rename, stars 하락, archived/private/deleted/topic 이탈 및 재활성화 테스트를 실행한다.
- [ ] concurrent/duplicate schedule 실행과 unique constraint 테스트를 실행한다.
- [ ] captured_at이 실제 측정 시각이며 UTC로 보존되는지 확인한다.

### 실행 기록

- 미실행

## Phase 9 — Ranking 계산과 원자적 공개

**목표:** PRD 공식과 baseline 정책으로 ranking을 계산하고 품질 기준을 만족한 run만 한 번에 공개한다.

**선행 조건:** Phase 8

### 구현 항목

- [ ] 각 repository의 실제 `captured_at`에서 24h/7d/30d `target_time`을 계산한다.
- [ ] target 이전의 가장 가까운 자체 snapshot이며 target과 차이가 최대 6시간인 경우만 실제 baseline으로 선택한다.
- [ ] 실제 baseline이 없을 때 7d/30d만 유효한 bootstrap baseline으로 fallback하고 `is_estimated=true`를 저장한다.
- [ ] 24h는 실제 baseline이 없으면 제외한다.
- [ ] `star_gain = current - baseline`, `score = ln((current+1)/(baseline+1))`를 구현하고 `star_gain > 0`만 저장한다.
- [ ] 정렬을 `score DESC → star_gain DESC → github_id ASC`로 고정한다.
- [ ] tracking 성공률을 `success / (success + failed)`로 계산하고 skipped는 분모에서 제외한다.
- [ ] 분모가 0이면 공개하지 않고, 성공률 95% 이상일 때만 ranking 전체 생성과 `published_at` 설정을 하나의 DB transaction으로 수행한다.
- [ ] 95% 미만이거나 계산/transaction이 실패하면 직전 공개 run을 유지한다.
- [ ] 카테고리별 ranking을 복제 저장하지 않고 topic mapping join으로 조회하며 repository 중복을 제거한다.

### 완료 조건

- [ ] 세 기간의 ranking이 PRD 공식과 baseline 허용 오차를 정확히 따른다.
- [ ] 일부 실패 run도 95% 이상이면 공개할 수 있고, 미만이면 공개되지 않는다.
- [ ] API가 읽는 published run에는 ranking 전체가 있거나 전혀 없다.
- [ ] `rankings.current_stars`가 공개 run의 snapshot과 일치한다.

### 테스트 방법

- [ ] target 직전/정확히 6시간/6시간 초과 baseline 선택 테스트를 실행한다.
- [ ] 24h bootstrap 금지, 7d/30d fallback, invalid bootstrap 제외 테스트를 실행한다.
- [ ] star 감소/0 gain 제외와 score 수치 테스트를 실행한다.
- [ ] score 동점, gain 동점, 최종 `github_id` 동점 해소 테스트를 실행한다.
- [ ] 94.99%, 95%, 100%, 분모 0 publication 판정 테스트를 실행한다.
- [ ] transaction 중 실패 시 직전 published run 유지 테스트를 실행한다.
- [ ] multi-topic category join 중복 제거 테스트를 실행한다.

### 실행 기록

- 미실행

## Phase 10 — FastAPI 읽기 전용 API

**목표:** GitHub를 호출하지 않고 PostgreSQL의 마지막 공개 데이터만 안정적으로 제공한다.

**선행 조건:** Phase 9

### 구현 항목

- [ ] `GET /rankings`에 period/category/page validation, 20개 pagination, PRD 정렬을 구현한다.
- [ ] 마지막 `published_at`이 있는 run만 읽고 `tracking_run_id`, `calculated_at`, page 정보를 반환한다.
- [ ] 공개 run이 없을 때 빈 ranking과 구분되는 명시적 데이터 준비 중 응답을 구현한다.
- [ ] category 미지정을 `All`로 처리하고 DB에 `All` row를 만들지 않는다.
- [ ] `GET /categories`가 활성 category를 `display_order` 순으로 모두 반환하며 결과 0건 category도 누락하지 않게 한다.
- [ ] `GET /repositories/{owner}/{name}`에 현재 metadata와 GitHub link를 구현한다.
- [ ] `GET /repositories/{owner}/{name}/star-history`에 최근 30일 실제 snapshot/bootstrap point와 점별 추정 여부를 구현한다.
- [ ] 실제 snapshot과 bootstrap이 겹치면 실제 값을 우선하고 bootstrap을 실제값으로 표시하지 않는다.
- [ ] `GET /health`는 process liveness, `GET /ready`는 DB 등 필수 의존성 readiness를 반환한다.
- [ ] user-facing API가 GitHubClient 또는 외부 network를 호출하지 않음을 보장한다.

### 완료 조건

- [ ] 네 endpoint와 health/readiness가 PRD 응답 상태를 구분한다.
- [ ] ranking page는 정확히 20개 단위이며 안정적인 정렬과 총 page 정보를 제공한다.
- [ ] category filter가 multi-topic repository를 중복 반환하지 않는다.
- [ ] API 데이터가 항상 공개 run/snapshot provenance를 유지한다.

### 테스트 방법

- [ ] period/category/page 정상·오류 및 첫/중간/마지막/범위 밖 page 테스트를 실행한다.
- [ ] published run 없음, 빈 결과, category 0건 테스트를 실행한다.
- [ ] 동점 정렬과 category 중복 제거 integration test를 실행한다.
- [ ] rename 후 현재 owner/name 상세 조회와 not-found 테스트를 실행한다.
- [ ] 30일 경계, estimated/actual 혼합, actual 우선 history 테스트를 실행한다.
- [ ] API 요청 중 outbound GitHub call이 0회인지 테스트한다.
- [ ] DB 정상/비정상 readiness 테스트를 실행한다.

### 실행 기록

- 미실행

## Phase 11 — Next.js ranking 화면

**목표:** 사용자가 공개 ranking을 기간과 category로 조회할 수 있게 한다.

**선행 조건:** Phase 10

### 구현 항목

- [ ] `All` 및 활성 category filter와 `24h | 7d | 30d` period filter를 구현한다.
- [ ] URL query에 period/category/page 상태를 반영해 새로고침과 공유가 가능하게 한다.
- [ ] 각 항목에 owner/name, 설명, star 수, growth score, star gain, 언어, category, GitHub link를 표시한다.
- [ ] 20개 단위 pagination UI를 구현한다.
- [ ] 공개 ranking 없음의 데이터 준비 중 상태와 정상 빈 결과를 구분한다.
- [ ] 결과가 0개인 활성 category도 filter에서 유지한다.
- [ ] loading, API error, retry 가능한 화면 상태와 기본 접근성을 구현한다.

### 완료 조건

- [ ] 모든 filter 조합과 pagination이 API 계약과 일치한다.
- [ ] 외부 GitHub link와 repository 상세 navigation이 동작한다.
- [ ] 데이터 준비 중, 빈 결과, 오류가 서로 다른 사용자 상태로 표시된다.
- [ ] 브라우저에서 GitHub API를 직접 호출하지 않는다.

### 테스트 방법

- [ ] filter/query-string/pagination component test를 실행한다.
- [ ] 0건 category, 준비 중, API 오류 rendering test를 실행한다.
- [ ] 항목 필드와 link rendering test를 실행한다.
- [ ] frontend lint, type check, production build를 실행한다.
- [ ] desktop/mobile viewport에서 수동 smoke test를 실행한다.

### 실행 기록

- 미실행

## Phase 12 — Repository 상세와 30일 star graph

**목표:** repository metadata와 최근 30일 star 추이를 실제/추정 구분과 함께 보여준다.

**선행 조건:** Phase 11

### 구현 항목

- [ ] owner/name route의 상세 metadata와 GitHub link를 구현한다.
- [ ] 최근 30일 star graph를 구현한다.
- [ ] 실제 snapshot과 bootstrap 추정 point를 색상/선 스타일/범례 등 시각적으로 구분한다.
- [ ] 30일 경계, 일부 데이터, 전부 실제, 실제+추정 혼합, 빈 history 상태를 처리한다.
- [ ] graph에 접근 가능한 label/summary와 추정치 설명을 제공한다.
- [ ] rename 이후 현재 route가 동작하도록 API의 현재 metadata를 사용한다.

### 완료 조건

- [ ] 사용자가 실제값과 추정값을 혼동하지 않고 구분할 수 있다.
- [ ] 최근 30일 밖의 점은 표시하지 않는다.
- [ ] bootstrap 누락 또는 일부 수집 실패가 page 전체 오류를 만들지 않는다.

### 테스트 방법

- [ ] actual-only, estimated-only, mixed, empty fixture component test를 실행한다.
- [ ] 30일 경계와 actual 우선 표시 테스트를 실행한다.
- [ ] 상세 not-found와 API 오류 상태 테스트를 실행한다.
- [ ] frontend lint, type check, production build를 실행한다.
- [ ] graph 범례와 접근성을 수동 검증한다.

### 실행 기록

- 미실행

## Phase 13 — Railway 운영 구성과 관찰 가능성

**목표:** API/web과 두 worker schedule을 Railway에서 안전하고 재실행 가능하게 운영한다.

**선행 조건:** Phase 12

### 구현 항목

- [ ] Railway의 web/API service와 동일 backend codebase의 worker entry point를 구성한다.
- [ ] daily discovery와 6시간 tracking/ranking을 별도 Railway Cron으로 구성한다.
- [ ] deploy/release 시 Alembic migration 실행 순서와 실패 시 중단 절차를 문서화한다.
- [ ] DB URL, GitHub token, API version 등 secret/config를 Railway 환경 변수로만 주입한다.
- [ ] UTC schedule과 애플리케이션 UTC 설정을 명시한다.
- [ ] `run_id`, `repository_id`, response status, retry count, duration을 포함한 구조화 로그를 구현한다.
- [ ] 실패 run/구간의 안전한 수동 재실행 절차를 문서화한다.
- [ ] health/readiness와 cron exit code가 Railway에서 실패를 식별하게 한다.

### 완료 조건

- [ ] 중복 cron 실행이 DB guard에 의해 차단된다.
- [ ] worker 실패가 published ranking을 손상시키지 않고 non-zero exit/log로 관찰된다.
- [ ] secret이 repository, image, log에 노출되지 않는다.
- [ ] 운영자가 discovery 실패 구간과 tracking partial failure를 run id로 추적할 수 있다.

### 테스트 방법

- [ ] Railway와 동일한 command로 API, discovery, tracking을 staging에서 smoke test한다.
- [ ] 동일 scheduled slot 동시 실행 테스트를 수행한다.
- [ ] 의도적 부분 실패에서 exit/status/log/published ranking 유지 여부를 확인한다.
- [ ] migration, health, readiness, 환경 변수 누락 실패를 확인한다.
- [ ] secret scan과 로그 redaction 점검을 수행한다.

### 실행 기록

- 미실행

## Phase 14 — MVP 통합 인수 검증

**목표:** PRD 10절 완료 기준을 production-like 환경에서 끝까지 검증한다.

**선행 조건:** Phase 13

### 구현 항목

- [ ] category sync → discovery → bootstrap → tracking → ranking publication → API → UI 전체 흐름을 실행한다.
- [ ] 최소 24시간의 실제 snapshot이 필요한 24h ranking은 synthetic/integration fixture로 먼저 검증하고, staging에서는 시간이 쌓인 뒤 별도 확인한다.
- [ ] 실제 6시간 schedule 여러 회차에서 snapshot이 보존되고 bootstrap이 실제 snapshot으로 대체되는 경로를 확인한다.
- [ ] release checklist, rollback 절차, known limitation을 문서화한다.
- [ ] `docs/IMPLEMENTATION_PLAN.md`의 모든 완료 항목과 실행 기록을 최종 갱신한다.

### 완료 조건

- [ ] 매일 topic discovery가 신규 repository를 중복 없이 저장한다.
- [ ] 6시간 tracking이 snapshot을 수집하고 과거 snapshot을 보존한다.
- [ ] 24h/7d/30d ranking, category filter, pagination이 동작한다.
- [ ] 신규 repository가 7d/30d 추정 ranking에 참여하고 24h는 실제 history가 있을 때만 참여한다.
- [ ] 95% 미만 수집 실패가 직전 공개 ranking을 유지한다.
- [ ] 사용자가 ranking과 repository별 30일 star 추이를 웹에서 조회한다.
- [ ] 로그인, 알림, LLM 분류 등 MVP 제외 기능이 포함되지 않는다.

### 테스트 방법

- [ ] 전체 backend test, lint, type check를 실행한다.
- [ ] 전체 frontend test, lint, type check, production build를 실행한다.
- [ ] 빈 DB에서 migration과 seed 후 end-to-end flow를 실행한다.
- [ ] duplicate discovery, search 분할/미완료, bootstrap, baseline, 동점/filter, partial failure, 95% 판정, rename/비활성화, API pagination 회귀 suite를 실행한다.
- [ ] 실제/추정 graph 구분과 데이터 준비 중 상태를 수동 acceptance test한다.

### 실행 기록

- 미실행

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

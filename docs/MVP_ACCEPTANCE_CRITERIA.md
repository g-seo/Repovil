# AI OSS Momentum Tracker — MVP 인수 계약

## 1. 목적과 적용 규칙

이 문서는 `docs/PRD.md`를 구현과 테스트에서 판정 가능한 계약으로 옮긴 것이다. 제품 요구사항의 Source of Truth는 PRD이며, 이 문서가 PRD와 충돌하면 PRD를 따른다.

- 각 요구사항 ID는 `docs/IMPLEMENTATION_PLAN.md`의 구현 Phase와 테스트에 연결한다.
- 아래에서 `MUST`는 MVP 완료에 필수, `MUST NOT`은 금지, `MAY`는 허용을 의미한다.
- timestamp 비교와 저장은 UTC 기준이다. 단, GitHub bootstrap 원천의 일 경계는 GitHub 응답의 경계를 보존하며 실제 UTC snapshot으로 간주하지 않는다.
- 결정 레지스터의 확정 항목은 후속 Phase의 구현·테스트 계약으로 사용한다.

## 2. 용어

| 용어 | 계약 |
|---|---|
| eligible repository | 활성 설정 topic 중 하나 이상, public, non-fork, non-archived, stars 200 이상인 repository |
| tracking 대상 | bootstrap을 마치고 현재 eligible 상태로 활성화된 repository |
| 자체 snapshot | tracking worker가 GitHub에서 성공적으로 측정해 실제 `captured_at`과 함께 저장한 star count |
| bootstrap point | GitHub star history의 `stars_created`와 최신 자체 snapshot으로 역산한 추정값 |
| published run | 성공률 기준을 통과하고 ranking 전체가 원자적으로 저장된 뒤 `published_at`이 설정된 tracking run |
| `All` | 모든 category를 조회하는 UI/API filter. category 또는 topic DB row가 아님 |
| stale snapshot | 현재 tracking run에서 새로 측정한 값이 아닌 과거 snapshot |

## 3. Repository discovery와 category

### 인수 기준

- [ ] **DISC-01** Discovery는 `config/categories.yaml`의 활성 topic마다 하루 1회 Repository Search를 수행해야 한다. (Phase 3, 6)
- [ ] **DISC-02** 최초 발견 시 public, non-fork, non-archived, stars 200 이상을 모두 만족해야 저장할 수 있다. 200 미만 결과는 저장하면 안 된다. (Phase 6)
- [ ] **DISC-03** search 결과가 1,000개를 넘는 star 구간은 재분할해야 한다. `incomplete_results`, 검색 실패, rate limit, 분할 불가능 구간은 실패 구간으로 남기며 정상 완료로 처리하면 안 된다. (Phase 1, 6)
- [ ] **DISC-04** 여러 topic 검색에서 같은 repository가 반환되어도 `github_id` 기준 한 repository만 저장해야 한다. (Phase 4, 6)
- [ ] **DISC-05** rename/transfer는 동일 `github_id`의 owner/name/URL metadata 변경으로 처리하고 새 repository를 만들면 안 된다. (Phase 4, 6, 8)
- [ ] **DISC-06** 기존 repository가 200 미만, archived, private, deleted 또는 모든 설정 topic 이탈 상태가 되면 row와 history는 유지하되 tracking 및 공개 대상에서 비활성화해야 한다. (Phase 8)
- [ ] **DISC-07** 비활성 repository가 eligibility를 다시 만족하면 같은 `github_id`로 재활성화해야 한다. (Phase 6, 8)
- [ ] **CAT-01** PRD 3.1의 여섯 category와 topic을 내용 변경 없이 `config/categories.yaml`에 저장하고 DB에 idempotent하게 seed/sync해야 한다. (Phase 3, 4)
- [ ] **CAT-02** 한 repository의 여러 topic/category 관계를 보존하되 ranking 조회 결과는 repository별 중복을 제거해야 한다. (Phase 6, 9, 10)
- [ ] **CAT-03** `All`은 YAML, search topic, DB category로 생성하면 안 된다. (Phase 3, 10, 11)
- [ ] **CAT-04** 활성 category는 현재 ranking 결과가 0개여도 `display_order` 순서로 노출해야 한다. (Phase 10, 11)
- [ ] **CAT-05** topic 분류에 LLM 검증을 사용하면 안 된다. (전 Phase)
- [ ] **CAT-06** YAML에서 제거된 category/topic과 해당 활성 mapping은 hard delete하지 않고 soft-deactivate해야 한다. 재추가 시 기존 row를 재활성화해야 한다. (Phase 3, 4, 6, 10)

### 필수 경계·실패 테스트

- 199/200 stars 경계와 추적 후 200 미만 하락
- 동일 repository의 여러 topic/category 중복
- rename, owner transfer, archived/private/deleted, 모든 설정 topic 이탈, 재활성화
- Search 999/1,000/1,001건, 포함 경계가 맞닿는 star 범위, `incomplete_results`, 중간 page 실패
- 동일 discovery 및 category sync의 반복 실행

## 4. Historical bootstrap과 snapshot

### 인수 기준

- [ ] **BOOT-01** 신규 eligible repository는 GitHub star history 원천을 별도 보존한 뒤 tracking을 활성화해야 한다. (Phase 7)
- [ ] **BOOT-02** bootstrap은 최신 자체 snapshot에서 일별 `stars_created`를 역산한 추정값이어야 한다. (Phase 7)
- [ ] **BOOT-03** bootstrap은 unstar를 정확히 복원하지 못하고 일 경계가 UTC와 다를 수 있으므로 항상 추정값으로 표시해야 한다. (Phase 7, 10, 12)
- [ ] **BOOT-04** 음수 baseline, 필요한 원천 누락 등 유효하지 않은 bootstrap은 ranking이나 graph의 유효값으로 사용하면 안 된다. 임의로 0을 넣으면 안 된다. (Phase 7, 9, 10)
- [ ] **BOOT-05** bootstrap은 7d/30d ranking과 30일 graph에만 사용할 수 있으며 24h ranking에는 사용할 수 없다. (Phase 7, 9)
- [ ] **SNAP-01** tracking은 6시간마다 실행하며 실제 GitHub 측정 시각과 star count를 새 자체 snapshot으로 저장해야 한다. (Phase 8)
- [ ] **SNAP-02** repository 수집 실패 시 해당 run의 snapshot을 생성하지 않고 과거 snapshot을 현재값으로 복사하면 안 된다. (Phase 8)
- [ ] **SNAP-03** snapshot과 bootstrap 원천 데이터는 삭제하거나 과거값을 덮어쓰면 안 된다. (Phase 4, 7, 8)
- [ ] **SNAP-04** 충분한 자체 snapshot이 있으면 bootstrap보다 자체 snapshot을 우선해야 한다. (Phase 9, 10, 12)

### 상세 graph 우선순위 사례

| 입력 | 기대 결과 |
|---|---|
| 같은 시점/표시 구간에 자체 snapshot과 bootstrap point가 모두 존재 | 자체 snapshot을 표시하고 실제값으로 표기한다. bootstrap은 실제값을 덮어쓰지 않는다. |
| bootstrap만 존재 | 점을 표시할 수 있으나 `is_estimated=true`이며 UI에서 실제값과 시각적으로 구분한다. |
| 자체 snapshot만 존재 | 실제 point로 표시한다. |
| bootstrap 계산이 음수 또는 원천 누락으로 유효하지 않음 | 해당 추정 point를 만들지 않는다. 0으로 표시하지 않는다. |
| 최근 30일 밖의 point | 상세 graph 응답과 화면에서 제외한다. |
| 일부 날짜/시간에 값이 없음 | 존재하는 유효 point만 반환한다. 결측을 0 또는 직전값으로 채우지 않는다. |

### 필수 경계·실패 테스트

- 일별 생성 수 역산, unstar 때문에 생성 수 합계와 최신 count가 어긋나는 경우
- 음수 baseline, 원천 누락, 중복 fetch, page 경계와 API 실패
- 24h 경로가 bootstrap을 참조하지 않는지 검증
- 실제/추정 중첩, 실제-only, 추정-only, 혼합, 빈 30일 history

## 5. Tracking run 결과 판정

### 공통 판정 원칙

- run 시작 시 tracking 대상 목록을 확정한다.
- repository 하나는 해당 run에서 정확히 하나의 결과(`success`, `failed`, `skipped`)를 가져야 한다.
- retry 가능한 오류는 제한된 exponential backoff 후 최종 판정한다.
- 과거 snapshot의 존재 여부는 현재 run의 결과를 성공으로 바꾸지 않는다.

### 판정표

| 상황 | 결과 | snapshot | 성공률 분모 | 후속 상태 |
|---|---|---:|---:|---|
| 현재 star 수와 상태를 성공적으로 조회했고 eligible | `success` | 새 snapshot 저장 | 포함 | active 유지 |
| timeout, connection error, retry 소진 5xx | `failed` | 저장 안 함 | 포함 | 현재 상태 유지, 오류 기록 |
| rate limit/secondary limit이 run의 retry 정책 안에 회복되지 않음 | `failed` | 저장 안 함 | 포함 | 현재 상태 유지, 오류 기록 |
| 인증/권한 설정 자체가 잘못되어 run을 계속할 수 없음 | run 자체 `FAILED`; 처리 못 한 대상은 `failed` | 저장 안 함 | 포함 | 운영 오류 기록 |
| run 대상 확정 후 이미 비활성화된 것으로 확인된 대상 | `skipped` | 저장 안 함 | 제외 | inactive 유지 |
| stars 200 미만, archived 또는 모든 설정 topic 이탈을 정상 응답으로 확인 | `skipped` | 저장 안 함 | 제외 | inactive 전환 |
| deleted/private를 tracking 도중 처음 확인 | `skipped` | 저장 안 함 | 제외 | inactive 전환 및 기록 보존 |

### Run status와 공개 판정

- [ ] **TRACK-01** 같은 UTC schedule slot은 `scheduled_at` uniqueness와 DB guard로 중복 실행할 수 없다. (Phase 4, 8)
- [ ] **TRACK-02** `success + failed + skipped = total_count`여야 한다. (Phase 8)
- [ ] **TRACK-03** 실패가 0이고 실행 자체가 성공하면 `COMPLETED`다. (Phase 8)
- [ ] **TRACK-04** 성공과 실패가 함께 있으면 `PARTIAL`이다. `PARTIAL`도 공개 기준을 만족할 수 있다. (Phase 8, 9)
- [ ] **TRACK-05** 전부 실패하거나 실행 자체가 실패하면 `FAILED`다. (Phase 8)
- [ ] **PUB-01** 성공률은 `success / (success + failed)`이고 skipped는 분자와 분모 모두에서 제외한다. (Phase 9)
- [ ] **PUB-02** 성공률 분모가 0이면 공개하면 안 된다. (Phase 9)
- [ ] **PUB-03** 성공률이 95% 이상일 때만 동일 run의 ranking 전체를 원자적으로 공개하고 `published_at`을 설정한다. (Phase 9)
- [ ] **PUB-04** 성공률이 95% 미만이거나 ranking transaction이 실패하면 직전 published run을 그대로 유지해야 한다. (Phase 9)
- [ ] **PUB-05** run status와 공개 여부는 독립적이다. `published_at`만 공개 여부를 나타낸다. (Phase 9, 10)

### 필수 경계·실패 테스트

- 전체 성공, 일부 실패, 전부 실패, skipped-only, 분모 0
- 성공률 94.99%, 정확히 95%, 100%
- 같은 schedule slot 동시 실행과 재실행
- target 확정 뒤 repository 상태 변경
- ranking transaction 실패 시 이전 published run 유지

## 6. Ranking 계약

### 계산

각 성공 repository와 각 `period ∈ {24h, 7d, 30d}`에 대해 다음을 적용한다.

```text
target_time = snapshot.captured_at - period
baseline = target_time 이전의 가장 가까운 자체 snapshot
star_gain = snapshot.star_count - baseline_stars
score = ln((snapshot.star_count + 1) / (baseline_stars + 1))
```

- [ ] **RANK-01** 자체 baseline은 target 이전이어야 하며 target과의 차이가 최대 6시간이어야 한다. (Phase 9)
- [ ] **RANK-02** 유효한 자체 baseline이 없으면 7d/30d에 한해 유효 bootstrap을 사용할 수 있고 `is_estimated=true`로 저장해야 한다. (Phase 9)
- [ ] **RANK-03** 24h에 유효한 자체 baseline이 없으면 그 repository를 해당 기간 ranking에서 제외해야 한다. (Phase 9)
- [ ] **RANK-04** 자체 snapshot과 bootstrap이 모두 없거나 추정치가 유효하지 않으면 제외해야 하며 baseline을 0으로 만들면 안 된다. (Phase 9)
- [ ] **RANK-05** `star_gain > 0`인 결과만 저장·표시해야 한다. (Phase 9, 10)
- [ ] **RANK-06** 정렬은 `score DESC`, `star_gain DESC`, `github_id ASC` 순서여야 한다. (Phase 9, 10)
- [ ] **RANK-07** 계산과 표시에 사용하는 현재 star 수는 같은 published run의 `rankings.current_stars`여야 한다. (Phase 9, 10)
- [ ] **RANK-08** category별 ranking을 중복 저장하지 않고 repository/topic/category 관계로 filter해야 한다. (Phase 9, 10)

### 필수 경계·실패 테스트

- target과 정확히 일치, target 직전, 허용 오차 정확히 6시간, 6시간 초과
- star gain 음수/0/양수와 score 수치
- score 동점, gain 동점, 최종 `github_id` 정렬
- 유효 자체 baseline과 bootstrap이 함께 있을 때 자체 baseline 우선
- multi-topic/category join 결과 중복 제거

## 7. 읽기 전용 API 의미 계약

구체적인 field naming은 API 구현 시 schema로 고정하되 다음 상태는 반드시 구분 가능해야 한다.

### Ranking collection

| 상태 | HTTP | 필수 의미 |
|---|---:|---|
| 아직 published run 없음 | `200` | `state=preparing`, `tracking_run_id=null`, `calculated_at=null`, `items=[]`; 정상 빈 결과와 구분 |
| published run은 있으나 filter 결과 없음 | `200` | `state=ready`, published run의 ID/계산 시각, `items=[]`, 유효한 pagination metadata |
| published run과 결과 있음 | `200` | `state=ready`, published run의 ID/계산 시각, 정렬된 최대 20개 items와 pagination metadata |
| 잘못된 period/category/page | `4xx` | 어떤 입력이 잘못됐는지 식별 가능한 validation error |

### 단일 repository와 history

| 상태 | HTTP | 필수 의미 |
|---|---:|---|
| 현재 owner/name에 해당하는 repository 존재 | `200` | 저장된 현재 metadata 반환; GitHub를 호출하지 않음 |
| repository history 존재 | `200` | 최근 30일 유효 point와 각 point의 추정 여부 반환 |
| repository는 있으나 최근 30일 point 없음 | `200` | 빈 point 배열 반환 |
| repository 없음 | `404` | 상세/history에서 동일한 안정적 error code와 message 사용 |

### Category와 health

- `GET /categories`는 활성 category 전체를 결과 수와 무관하게 `display_order` 순으로 반환한다.
- `GET /health`는 process liveness만 판정한다.
- `GET /ready`는 최소한 DB 연결 실패를 readiness 실패로 반환한다.
- 사용자 API와 Next.js의 사용자 요청은 GitHub API를 호출하면 안 된다.

### Pagination 최소 계약

- page는 1부터 시작한다.
- page size는 20으로 고정한다.
- 응답은 현재 page, page size, total items, total pages를 구분할 수 있어야 한다.
- 범위 밖의 유효한 양수 page는 ready 상태의 빈 items로 처리하고, 0/음수/정수가 아닌 page는 validation error로 처리한다.

## 8. 화면 인수 기준

- [ ] **UI-01** ranking 화면은 `All`/활성 category와 `24h | 7d | 30d` filter를 제공한다. (Phase 11)
- [ ] **UI-02** ranking item은 owner/name, 설명, star 수, growth score, star gain, 언어, category, GitHub link를 표시한다. (Phase 11)
- [ ] **UI-03** 한 page에 최대 20개를 표시하고 filter/page 상태를 URL로 복원할 수 있다. (Phase 11)
- [ ] **UI-04** 데이터 준비 중, ready이지만 빈 결과, API 오류를 서로 다르게 표시한다. (Phase 11)
- [ ] **UI-05** 상세 화면은 repository 기본 정보, GitHub link, 최근 30일 star graph를 표시한다. (Phase 12)
- [ ] **UI-06** graph는 실제 snapshot과 bootstrap 추정치를 시각적 스타일과 범례/설명으로 구분한다. (Phase 12)
- [ ] **UI-07** 로그인, 저장/watchlist, 알림, 비교/추천, LLM 분석/분류, 관리자 UI를 제공하지 않는다. (전 Phase)

## 9. 운영·아키텍처 인수 기준

- [ ] **ARCH-01** 모든 GitHub API 호출은 background worker의 `GitHubClient`를 통한다. (Phase 5~8)
- [ ] **ARCH-02** user-facing API는 PostgreSQL만 읽고 GitHubClient나 외부 GitHub API를 호출하지 않는다. (Phase 5, 10)
- [ ] **ARCH-03** discovery와 tracking 책임을 분리하고 tracking과 ranking은 하나의 통제된 pipeline으로 실행한다. (Phase 6, 8, 9)
- [ ] **ARCH-04** schema 변경은 Alembic migration으로 수행한다. (Phase 4 이후)
- [ ] **ARCH-05** job은 DB 기반으로 중복 실행을 방지하고 실패 후 재실행 가능해야 한다. (Phase 6, 8, 13)
- [ ] **OPS-01** discovery는 daily, tracking/ranking은 6시간마다 Railway Cron으로 실행한다. (Phase 13)
- [ ] **OPS-02** 구조화 로그는 해당 시점에 적용 가능한 `run_id`, `repository_id`, response status, retry count, duration을 포함한다. (Phase 5, 6, 8, 13)
- [ ] **OPS-03** secret은 Railway 환경 변수로만 제공하고 repository, fixture, log에 기록하지 않는다. (Phase 2, 13)
- [ ] **ARCH-06** Redis, Celery, Kafka, Kubernetes를 도입하지 않는다. (전 Phase)

## 10. PRD MVP 완료 기준 추적

| PRD 10절 | Acceptance IDs | 구현 Phase | 필수 검증 |
|---:|---|---|---|
| 1 | DISC-01~07, CAT-01~06 | 3, 4, 6 | 설정 일치, search 분할, 중복 discovery, identity/상태 전이 |
| 2 | SNAP-01~04, TRACK-01~05 | 4, 8 | 6시간 run, 실제 측정 시각, history 보존, partial failure |
| 3 | RANK-01~08, CAT-02~04, UI-01~04 | 9, 10, 11 | 세 기간, 정렬, filter, 20개 pagination |
| 4 | BOOT-01~05, RANK-02~04, UI-06 | 7, 9, 12 | bootstrap 추정, 24h 금지, actual 우선 표시 |
| 5 | SNAP-02, PUB-01~05 | 8, 9 | 95% 경계, 원자적 공개, 직전 ranking 유지 |
| 6 | UI-01~06, ARCH-02 | 10, 11, 12 | DB-only API, ranking 화면, 상세 30일 graph |

모든 PRD MVP 완료 기준은 구현 Phase와 정상·경계·실패 검증에 연결되어 있다.

## 11. MVP 제외 범위 점검

다음 기능은 acceptance 대상이 아니며 구현 계획의 어떤 Phase에서도 구현하지 않는다.

- 로그인과 사용자 계정
- 저장, watchlist, 알림
- repository 비교 또는 추천
- LLM 분석·분류와 관리자 UI
- GraphQL tracking 전환, webhook, snapshot downsampling
- Redis, Celery, Kafka, Kubernetes와 범용 orchestration

## 12. 결정 레지스터

아래 항목은 PRD만으로 단일 구현을 확정할 수 없어 사용자 결정을 받은 사항이다. 이 결정은 관련 Phase의 구현·테스트 계약으로 사용한다.

| ID | 상태 | 결정 대상 | 확정 내용 | 영향 Phase |
|---|---|---|---|---:|
| DEC-01 | 확정 (2026-10-10) | tracking 도중 처음 확인된 deleted/private의 run 집계 | `skipped`. transient 수집 실패가 아니라 eligibility 상실로 처리하고 inactive로 전환 | 8, 9 |
| DEC-02 | 확정 (2026-10-10) | repository 상세/history의 not-found wire response | 두 endpoint 모두 HTTP `404`, 동일한 안정적 error code와 message 사용 | 10~12 |
| DEC-03 | 확정 (2026-10-10) | YAML에서 제거된 category/topic의 DB sync 정책 | row/history는 보존하고 누락 항목과 해당 활성 mapping을 soft-deactivate. 재추가 시 같은 row를 재활성화 | 3, 4, 6, 10 |

구현 제약:

- deleted/private를 구현 편의에 따라 임의 집계하지 않는다.
- 상세와 history가 서로 다른 not-found 의미를 갖게 하지 않는다.
- 설정에서 사라진 row나 과거 repository 관계/history를 hard delete하지 않는다.

# AI OSS Momentum Tracker — MVP PRD

## 1. 목표와 범위

GitHub의 AI 오픈소스 중 **최근 star 증가 비율이 높은 repository**를 발견하는 읽기 전용 웹 서비스.

- 대상: AI·Software Engineer
- 제공: 24h / 7d / 30d 성장 랭킹, 카테고리 필터, repository 상세 및 30일 star 그래프
- MVP 제외: 로그인, 저장·watchlist·알림, 비교·추천, LLM 분석·분류, 관리자 UI

## 2. 화면

**랭킹 페이지**
- 필터: `All` 또는 카테고리, 기간 `24h | 7d | 30d`
- 항목: `owner/name`, 설명, star 수, growth score, star gain, 언어, 카테고리, GitHub 링크
- 한 페이지 20개. 활성 카테고리는 결과가 0개여도 노출
- 공개된 랭킹이 없으면 데이터 준비 중 상태 표시

**상세 페이지**
- repository 기본 정보, 최근 30일 star 그래프, GitHub 링크
- 추정된 과거 데이터와 실제 snapshot을 시각적으로 구분

## 3. Repository 선정과 카테고리

- Discovery 대상: `3.1 초기 Topic 매핑`에 정의된 활성 GitHub Topics 중 하나 이상을 가진 **public, non-fork, non-archived** repository, **stars ≥ 200**
- 처음부터 200 미만인 repository는 저장하지 않음. 이후 200 이상이 되면 신규 발견
- 추적 중 200 미만, archived, private, deleted 또는 모든 설정 topic에서 이탈하면 기록은 유지하고 추적·공개 대상에서 비활성화. 다시 조건을 만족하면 재활성화
- 식별자: `github_id` (rename/transfer 시 동일 repository로 유지)
- 카테고리: `AI Agents`, `Skills`, `MCP Servers`, `Dev Tools`, `RAG`, `Observability&Eval`
- **`All`은 DB 카테고리가 아닌 전체 조회 필터**
- 아래 YAML을 초기 매핑의 기준으로 사용하고 `config/categories.yaml`에 동일하게 저장해 DB에 seed/sync. 다중 카테고리 허용, 조회 결과 중복 제거
- Topic 기반 분류는 휴리스틱이며, LLM 검증은 MVP에서 수행하지 않음

### 3.1 초기 Topic 매핑

```yaml
# 초기 MVP 카테고리/Topic 매핑. 운영 데이터를 보고 조정 가능.
# All은 DB category가 아닌 UI 전체 필터이므로 이 파일에 포함하지 않는다.
categories:
  - name: AI Agents
    slug: ai-agents
    active: true
    display_order: 1
    topics:
      - ai-agent
      - ai-agents
      - agentic-ai
      - ai-agent-framework

  - name: Skills
    slug: skills
    active: true
    display_order: 2
    topics:
      - agent-skills
      - ai-agent-skills
      - claude-code-skills
      - codex-skills

  - name: MCP Servers
    slug: mcp-servers
    active: true
    display_order: 3
    topics:
      - mcp-server
      - mcp-servers

  - name: Dev Tools
    slug: dev-tools
    active: true
    display_order: 4
    topics:
      - ai-coding
      - ai-coding-assistant
      - ai-developer-tools
      - coding-agents

  - name: RAG
    slug: rag
    active: true
    display_order: 5
    topics:
      - rag
      - retrieval-augmented-generation
      - vector-database

  - name: Observability&Eval
    slug: observability-eval
    active: true
    display_order: 6
    topics:
      - llm-observability
      - agent-observability
      - llm-evaluation
      - agent-evaluation
```

- 위 Topics는 MVP 초기 후보이며 운영 결과에 따라 조정 가능.
- `All`은 검색용 Topic 또는 DB 카테고리로 생성하지 않음.

## 4. 랭킹 산정

```text
period ∈ {24h, 7d, 30d}
target_time = snapshot.captured_at - period
baseline_stars = 유효한 target_time 이전 기준 star 수
star_gain = snapshot.star_count - baseline_stars
score = ln((snapshot.star_count + 1) / (baseline_stars + 1))
```

- **`star_gain > 0`만 표시**
- 정렬: `score DESC → star_gain DESC → github_id ASC`
- 각 repository의 **실제 `captured_at`** 기준으로 계산; 동일 tracking run 결과를 한 번에 공개
- Baseline: 목표 시각 **이전의 가장 가까운 자체 snapshot** 사용, 허용 오차 최대 6시간
- 유효한 자체 snapshot이 없을 때 **7d/30d만** historical bootstrap 사용; 결과에 `is_estimated=true`
- **24h는 bootstrap 금지**. 유효한 자체 snapshot이 확보된 뒤에만 랭킹 참여
- 자체 snapshot과 bootstrap 모두 없거나 추정치가 유효하지 않으면 해당 기간의 랭킹에서 제외; 임의로 0 처리하지 않음

### Historical bootstrap

- 신규 repository의 7d/30d 랭킹과 30일 그래프 초기 구간을 보완
- GitHub **repository star history API**의 일별 `stars_created`와 최신 실측 star 수로 과거 baseline을 **추정**
- API는 star 생성 수를 제공하므로 unstar를 정확하게 복원하지 못하고 일별 경계도 UTC와 정확히 일치하지 않을 수 있음. 따라서 bootstrap 수치는 **추정치**로만 사용
- 최신 자체 snapshot을 기준으로 필요한 일별 증가량을 역산. 추정 baseline이 음수 등 유효하지 않으면 사용하지 않음
- 충분한 자체 snapshot이 쌓이면 자동으로 bootstrap을 대체. 원천 데이터는 별도 보관

## 5. 수집 파이프라인

### Discovery — 하루 1회

1. 설정된 topic마다 GitHub Repository Search 수행
2. **Star 범위 분할 검색**으로 검색당 1,000건 제한에 대응. 과다한 구간은 재분할
3. `incomplete_results`, 검색 실패, rate limit을 확인하고 실패한 구간을 기록·재시도
4. 조건 검증 → `github_id` 중복 제거 → 신규 저장/기존 메타데이터·topic 갱신
5. 신규 대상의 historical bootstrap 수집 → tracking 활성화

GitHub 검색 범위·시간 제한상 완전한 전수 발견을 보장하지 않음. 미완료 검색은 정상 완료로 처리하지 않음.

### Tracking + Ranking — 6시간마다 한 파이프라인

1. 중복 실행을 방지하고 `tracking_run` 생성; 시작 시 대상 목록 확정
2. GitHub에서 현재 star 수 및 상태 조회, 실제 측정 시각과 함께 snapshot 저장
3. 일시 오류 재시도(exponential backoff); 실패한 repository는 **이번 run에서 제외**하고 과거 snapshot을 최신값으로 대체하지 않음
4. 성공한 repository만 24h/7d/30d 랭킹 산정
5. **성공률 ≥ 95%**면 새 랭킹 전체를 원자적으로 공개; 미달이면 직전 공개 랭킹 유지

성공률 = `success / (success + failed)`; 이미 추적 자격을 잃어 비활성화된 대상은 `skipped`로 기록하고 분모에서 제외. 분모가 0이면 공개하지 않음.

`tracking_run.status`: `RUNNING`(실행 중), `COMPLETED`(실패 0), `PARTIAL`(일부 실패), `FAILED`(전부 실패 또는 실행 자체 실패). `PARTIAL`이어도 공개 기준을 만족할 수 있음. 공개 여부는 `published_at`으로 별도 표시.

## 6. 기술 구조

```text
GitHub API
  ├─ Discovery Worker (daily)
  └─ Tracking/Ranking Worker (6h)
                 ↓
             PostgreSQL
                 ↓
               FastAPI
                 ↓
               Next.js
```

- Backend: **FastAPI / Python**, Frontend: **Next.js**, DB: **PostgreSQL**
- Deployment / Scheduling: **Railway / Railway Cron**
- 동일 backend 코드베이스에서 API와 worker entry point만 분리
- `GitHubClient`: `search_repositories`, `get_repository`, `get_repository_stats`, `get_star_history` 추상화. REST로 시작해 추후 tracking을 GraphQL 방식으로 교체 가능
- 페이지 요청 중 GitHub API 호출 금지. Redis·Celery·Kafka·Kubernetes 도입 금지

## 7. 데이터 모델 (핵심 필드)

| 테이블 | 핵심 필드/제약 |
|---|---|
| `repositories` | `id`, `github_id UNIQUE`, `owner`, `name`, `description`, `github_url`, `language`, `current_stars`, `status`, `discovered_at`, `tracking_started_at`, timestamps |
| `topics` / `categories` | `topics(name UNIQUE, active)` / `categories(name UNIQUE, slug UNIQUE, active, display_order)` |
| `category_topics` / `repository_topics` | 각 FK 쌍 `PRIMARY KEY`; 다대다 매핑 |
| `discovery_runs` | `id`, 시작/종료 시각, 발견·추가 수, `status`, 실패 구간 정보 |
| `tracking_runs` | `id`, `scheduled_at UNIQUE`, 시작/종료 시각, `total_count`, `success_count`, `failed_count`, `skipped_count`, `status`, `published_at NULLABLE` |
| `star_snapshots` | `id`, `tracking_run_id`, `repository_id`, `captured_at`, `star_count`; `UNIQUE(tracking_run_id, repository_id)` |
| `bootstrap_star_history` | `repository_id`, `date`, `stars_created`, `fetched_at`; `PRIMARY KEY(repository_id, date)` |
| `rankings` | `tracking_run_id`, `repository_id`, `period`, `score`, `star_gain`, `current_stars`, `is_estimated`, `calculated_at`; 복합 PK `(tracking_run_id, repository_id, period)` |

- Index: `star_snapshots(repository_id, captured_at DESC)`
- Snapshot은 삭제하지 않음. 과거 데이터 downsampling은 MVP 제외
- 카테고리별 랭킹을 별도로 저장하지 않고 `rankings → repository_topics → category_topics`로 조회
- 랭킹 표시 star 수는 `rankings.current_stars` 사용(해당 공개 run과 일치)

## 8. API (읽기 전용)

| Endpoint | 동작 |
|---|---|
| `GET /rankings?period=7d&category=ai-agents&page=1` | 마지막 공개 run에서 기간·카테고리 필터, 20개씩 페이지네이션; `tracking_run_id`, `calculated_at`, 페이지 정보 반환 |
| `GET /repositories/{owner}/{name}` | 상세 metadata (rename/transfer 반영) |
| `GET /repositories/{owner}/{name}/star-history` | 최근 30일 데이터, 각 점의 추정 여부 포함 |
| `GET /categories` | 활성 카테고리 (`display_order` 순), 0건도 포함 |
| `GET /health`, `GET /ready` | Liveness / DB 등 필수 의존성 readiness |

- `category` 미지정 = `All`; 결과 없으면 빈 배열
- 공개된 랭킹이 없으면 데이터 준비 중 상태를 명시적으로 반환

## 9. 운영 요건

- Schema migration: **Alembic**; 전 시간 **UTC** 저장
- Job idempotency / DB 기반 중복 실행 방지 / 실패 시 재실행 가능한 처리
- GitHub API timeout, retry+backoff, 4xx·5xx 구분, rate limit 관찰
- 구조화 로그: `run_id`, `repository_id`, 응답 상태, 재시도 횟수, 소요 시간
- Secret은 Railway 환경 변수 사용
- 테스트 필수: 중복 discovery, search 분할·미완료, bootstrap 추정, baseline 선택, ranking 동점/필터, partial failure, 95% 공개 판정, rename/비활성화, API pagination

## 10. MVP 완료 기준

1. 설정된 topic에서 매일 신규 repository를 발견하고 중복 없이 저장한다.
2. 추적 대상의 star snapshot을 6시간마다 수집·보존한다.
3. 24h/7d/30d 성장 랭킹과 카테고리 필터가 동작한다.
4. 신규 repository는 7d/30d bootstrap 추정 랭킹에 참여하고 24h는 실측 history가 확보되면 참여한다.
5. 일부 수집 실패가 기존 공개 랭킹을 손상시키지 않는다.
6. 사용자가 웹에서 랭킹과 repository별 star 추이를 조회한다.

---

설정 파일: [`config/categories.yaml`](config/categories.yaml) (3.1의 YAML과 동일).
GitHub API: [Search](https://docs.github.com/en/rest/search/search), [Star history](https://docs.github.com/en/rest/activity/starring).

# GitHub REST API 실현 가능성 검증

## 1. 검증 개요

- 검증 일자: 2026-10-10 (UTC)
- GitHub REST API version: `2026-03-10`
- 요청 헤더: `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2026-03-10`, 고정 `User-Agent`
- 인증: public repository read-only fine-grained token. token 값을 읽거나 출력하지 않고 GitHub CLI credential store를 통해 요청했다.
- 표본 repository: `octocat/Hello-World`(소형), `fastapi/fastapi`(중형), `freeCodeCamp/freeCodeCamp`(대형)
- 표본 topic: PRD의 21개 topic 전체, 분할 검증용 `ai`
- secret, token, 개인 정보, 전체 응답 body는 저장하지 않았다. 아래에는 재현에 필요한 요약만 남긴다.

결론: PRD의 discovery, current star count, 30일 bootstrap에 필요한 REST endpoint는 존재하고 public repository에서 인증/비인증 모두 동작했다. `2026-03-10`을 pin하면 PRD를 REST로 구현할 수 있다. 인증 Search/core 예산도 daily discovery와 6시간 tracking schedule을 지원한다.

## 2. API version과 권한

GitHub의 현재 지원 version은 `2026-03-10`, `2022-11-28`이고, 미지정 요청은 `2022-11-28`로 처리된다. star count/history를 포함한 현재 계약을 고정하기 위해 모든 `GitHubClient` 요청에 `X-GitHub-Api-Version: 2026-03-10`을 명시한다.

public repository는 검증한 모든 GET endpoint를 비인증으로 호출할 수 있었다. 공식 문서상 fine-grained PAT/GitHub App token은 repository `Metadata: read`로 count/history를 읽을 수 있다. 2026년 7월부터 제한된 것은 사용자 목록을 내려주는 `GET /stargazers`이며, MVP는 이 endpoint를 사용하지 않고 aggregate count/history만 사용한다.

동일한 `Metadata: read` token으로 Search와 소형/중형/대형 public repository의 metadata, count, history를 모두 재호출했고 HTTP 200을 확인했다. 응답에서 API version은 `2026-03-10`, core limit은 5,000/hour, Search limit은 30/minute였다.

## 3. Repository Search

### 요청 계약

`GET /search/repositories`에 다음 query를 결합한다.

```text
topic:{topic} stars:{lower}..{upper} fork:false archived:false is:public
sort=stars&order=desc&per_page=100&page={page}
```

live 응답은 `total_count`, `incomplete_results`, `items`, `Link` pagination header를 제공했다. `ai-agent`, `stars>=200`의 상위 결과는 `private=false`, `fork=false`, `archived=false`, `visibility=public`, topic 포함, star 하한 이상을 모두 만족했다.

### 범위와 1,000건 제한

- `topic:ai`, `stars:200..200` = 8건
- `topic:ai`, `stars:201..201` = 5건
- `topic:ai`, `stars:200..201` = 13건

양 끝이 모두 포함되므로 인접 분할은 `[lower..mid]`, `[mid+1..upper]`로 생성해야 한다.

`topic:ai`, eligible query는 4,131건을 반환했지만 접근할 수 있는 결과는 처음 1,000건이다. `per_page=100&page=10`은 100건, `page=11`은 HTTP 422와 `Only the first 1000 search results are available`를 반환했다.

같은 query를 star로 재귀 분할한 결과는 다음과 같다.

| star 구간 | `total_count` | 판정 |
|---|---:|---|
| 200..999 | 2,478 | 재분할 필요 |
| 200..499 | 1,657 | 재분할 필요 |
| 200..299 | 829 | 수집 가능 |
| 300..499 | 828 | 수집 가능 |
| 500..999 | 821 | 수집 가능 |
| 1,000..4,999 | 1,116 | 재분할 필요 |
| 1,000..1,999 | 619 | 수집 가능 |
| 2,000..4,999 | 497 | 수집 가능 |
| 5,000..* | 537 | 수집 가능 |
| 200..200 | 8 | 단일 star 값도 종료 가능 |

이 표본은 재귀 분할이 실제로 모든 leaf를 1,000건 이하로 만들 수 있음을 보여준다. 현재 설정 topic에서 단일 star 값이 1,000건을 넘는 사례는 관찰되지 않았다. 그런 구간이 발생하면 더 분할하지 못하므로 failure range로 남긴다.

1,000건 이하 pagination은 `mcp-server` 724건으로 확인했다. `per_page=100` 기준 page 8은 24건, page 9는 빈 배열을 HTTP 200으로 반환했다. Search에 `per_page=101`을 보내면 거부하지 않고 100건으로 clamp했다. client는 명시적으로 100을 사용한다.

`incomplete_results`는 모든 live 표본에서 `false`였다. 필드가 `true`이면 items가 있어도 해당 구간을 성공으로 처리하지 않고 failure range로 저장한다.

## 4. Repository metadata, count, history

| `GitHubClient` 메서드 | REST endpoint | live 검증 결과 |
|---|---|---|
| `search_repositories` | `GET /search/repositories` | topic/eligibility/sort/pagination, `total_count`, `incomplete_results` 확인 |
| `get_repository` | `GET /repos/{owner}/{repo}` | `id`(`github_id`), owner/name, URL, topics, visibility, fork, archived, `stargazers_count` 확인 |
| `get_repository_stats` | `GET /repos/{owner}/{repo}/stargazers/count` | `{ "count": integer }` 확인 |
| `get_star_history` | `GET /repos/{owner}/{repo}/stargazers/history` | 최신순 주간 배열, `week`, `total`, 7개 `days` 확인 |

`GET /repos/tiangolo/fastapi`는 HTTP 301과 `Location: /repositories/160919119`를 반환했고 redirect 후 `fastapi/fastapi`, `id=160919119`를 반환했다. client는 safe GET redirect를 따르고 항상 `github_id`를 identity로 사용한다. 없는 repository는 HTTP 404, `message=Not Found`였다.

count smoke result는 검증 시점에 `octocat/Hello-World` 3,803, `fastapi/fastapi` 102,963, `freeCodeCamp/freeCodeCamp` 456,810이었다. 이 값은 시간에 따라 변하므로 test fixture의 고정 기대값으로 사용하지 않는다.

history는 최신 주부터 과거로 pagination되고 한 page의 최대는 30주, page는 최대 100이다. `per_page=31`은 30건으로 clamp되고 `page=101`은 HTTP 422, `Pagination is limited to 100 pages.`를 반환했다. 30일 bootstrap은 page 1 한 번으로 충분하다.

`week`는 Unix epoch이고 `days`는 일요일부터 7개 값이다. 공식 계약은 week/day 경계가 UTC와 일치한다고 보장하지 않으므로, 이 값을 actual snapshot timestamp로 해석하지 않는다.

`fastapi/fastapi`의 410주 history를 모두 합산한 결과는 현재 count 102,963과 같았다. 응답은 star가 생성된 day의 집계만 제공하고 unstar event/time을 제공하지 않는다. 따라서 역산 baseline은 과거 실측치가 아닌 추정치이며, unstar를 복원한다고 간주하면 안 된다.

## 5. Rate limit과 실패 처리 계약

live 비인증 header는 Search `10/minute`, core `60/hour`를 보였고, 모든 응답에 `x-ratelimit-limit`, `x-ratelimit-remaining`, `x-ratelimit-reset`, `x-ratelimit-resource`가 있었다. 공식 계약상 일반 인증 요청은 core `5,000/hour`, repository Search는 별도 bucket `30/minute`를 사용한다. secondary limit은 보장된 잔여량 조회가 없으므로 응답을 기준으로 처리한다.

인증 live request에서도 core `5,000/hour`, Search `30/minute`를 직접 확인했다. `GET /rate_limit`의 resource body와 개별 Search/repository 응답 header가 일치했다.

우선순위는 다음과 같다.

1. HTTP 403/429에 `Retry-After`가 있으면 그 초 이후까지 기다린다.
2. `x-ratelimit-remaining=0`이면 `x-ratelimit-reset` UTC epoch까지 기다린다.
3. 두 정보가 없는 secondary-limit 403/429는 최소 60초 후 bounded exponential backoff로 재시도한다.
4. timeout, connection error, 5xx도 bounded exponential backoff 대상이다.
5. 404는 not-found/자격 상태 확인, 401/403 authentication failure는 설정 오류, 422 query/pagination validation은 비재시도 오류로 구분한다. 단, 403의 body/header가 rate limit을 명시하면 위 재시도 규칙을 적용한다.

실제 오류 fixture로 보존할 최소 형태는 다음과 같다. 403/429는 고의로 limit을 소진하지 않고 공식 계약을 Phase 5 fixture로 고정한다.

```json
{
  "status": 404,
  "body": {"message": "Not Found", "status": "404"}
}
```

```json
{
  "status": 422,
  "body": {
    "message": "Only the first 1000 search results are available",
    "status": "422"
  }
}
```

```json
{
  "status": 429,
  "headers": {
    "retry-after": "60",
    "x-ratelimit-remaining": "0",
    "x-ratelimit-reset": "<UTC epoch>"
  },
  "body": {"message": "<rate limit message>"}
}
```

## 6. 규모 추정과 요청 예산

2026-10-10에 PRD의 각 topic을 `stars>=200`, public, non-fork, non-archived로 조회한 `total_count`는 다음과 같다. 값은 시간에 따라 변한다.

| Category | topic counts | 합계(중복 포함) |
|---|---|---:|
| AI Agents | 800, 1,783, 602, 19 | 3,204 |
| Skills | 614, 8, 84, 55 | 761 |
| MCP Servers | 724, 61 | 785 |
| Dev Tools | 217, 58, 11, 164 | 450 |
| RAG | 755, 159, 179 | 1,093 |
| Observability&Eval | 29, 22, 66, 16 | 133 |
| 전체 |  | 6,426 |

중복 제거 전의 보수적 상한은 6,426개고, 합집합의 하한은 가장 큰 topic의 1,783개다. 정확한 unique 개수는 discovery가 모든 page를 수집한 후 `github_id`로 확정한다.

- Daily discovery: 단순 page 수는 76회이며 1,000건 초과 topic의 분할 probe를 포함해 약 78회 이상이다. 인증 Search 30/minute에서 약 3분에 처리 가능하다.
- Tracking: repository당 metadata/count 1회면 1,783~6,426 core request, 둘을 분리해 2회로 잡아도 3,566~12,852 request다. 5,000/hour 기준 최대 약 2.57시간으로 6시간 schedule 안에 들어온다.
- Initial bootstrap: 30일 history는 repository당 1회면 되므로 상한 6,426 request, 약 1.29시간이다. metadata/count를 추가해도 초기 일회성 작업을 6시간 안에 pacing할 수 있다.
- Secondary limit을 피하기 위해 Search/core bucket을 따로 관찰하고, 동시 요청을 100개 미만으로 유지하며, response header에 따라 pacing한다.

따라서 현재 표본 규모는 daily discovery와 6시간 tracking schedule에서 운영 가능하다. 다만 개발/운영은 비인증 limit이 아닌 read-only token을 사용해야 하고, run 시작 전 실제 대상 수로 예산을 다시 계산해야 한다.

## 7. 문서 기준선과 live 차이

- 공식 문서와 live 응답 모두 API version `2026-03-10`을 선택했다.
- 문서의 Search 1,000건 제한은 live `page=11` 422로 확인됐다.
- 문서는 `per_page` 최대를 Search 100, history 30으로 명시하지만 live API는 초과 값을 422로 거부하지 않고 각각 100, 30으로 clamp했다. client는 문서 최대를 직접 지켜서 clamp에 의존하지 않는다.
- history `page=101`은 문서와 같이 422였다.
- 단일 star 값 1,000건 초과, `incomplete_results=true`, 403/429는 안전상 인위적으로 만들지 않았다. Phase 5/6에서 위 계약으로 fixture 테스트한다.

## 8. 인증 smoke 결과

| 표본 | metadata | count | history | 일관성 |
|---|---:|---:|---:|---|
| `octocat/Hello-World`(소형) | 200 | 200 | 200 | metadata/count 3,803 일치 |
| `fastapi/fastapi`(중형) | 200 | 200 | 200 | metadata/count 102,963 일치 |
| `freeCodeCamp/freeCodeCamp`(대형) | 200 | 200 | 200 | metadata/count 456,810 일치 |

Search는 HTTP 200, `total_count=800`, `incomplete_results=false`, `x-ratelimit-resource=search`, `x-ratelimit-limit=30`을 반환했다. repository endpoint는 `x-ratelimit-resource=core`, `x-ratelimit-limit=5000`을 반환했다. 모든 응답의 selected API version은 `2026-03-10`이었다.

token은 GitHub CLI credential store에서 직접 사용했고 command, stdout/stderr, fixture, 문서에 값을 출력하지 않았다. Phase 1의 검증 gate는 모두 통과했다.

## 9. 공식 자료

- [Repository Search REST API](https://docs.github.com/en/rest/search/search?apiVersion=2026-03-10#search-repositories)
- [Starring REST API](https://docs.github.com/en/rest/activity/starring?apiVersion=2026-03-10)
- [Repository REST API](https://docs.github.com/en/rest/repos/repos?apiVersion=2026-03-10#get-a-repository)
- [REST API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api?apiVersion=2026-03-10)
- [REST API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions)

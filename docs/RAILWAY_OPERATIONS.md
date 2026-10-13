# Railway 운영 가이드

이 문서는 MVP의 Railway 서비스 구성, release 순서, 관찰 및 안전한 수동 재실행 절차를 고정한다. 모든 schedule과 애플리케이션 timestamp는 UTC다.

## 서비스 구성과 IaC 경계

`.railway/railway.ts` 하나가 같은 Git repository의 PostgreSQL과 네 service를 프로젝트 단위로 선언한다.

| Resource | 역할 | Schedule |
|---|---|---|
| `Postgres` | API와 worker의 영속 저장소 | 상시 |
| `repovil-api` | FastAPI read-only API | 상시 |
| `repovil-web` | Next.js web | 상시 |
| `repovil-daily` | discovery 후 pending bootstrap | `0 3 * * *` UTC |
| `repovil-tracking` | snapshot 수집과 ranking 공개 | `0 */6 * * *` UTC |

Cron process는 작업 후 연결을 닫고 종료한다. Railway는 이전 실행이 남아 있으면 다음 cron 실행을 건너뛰므로 DB advisory lock은 Railway 외 수동 실행과 경합하는 경우까지 방어한다. Railway의 [Cron Jobs](https://docs.railway.com/cron-jobs) 문서에 따라 schedule은 UTC이며 정확히 분 단위 시작을 보장하지 않는다.

Railway IaC는 이 repository 전체가 소유하는 리소스를 모두 한 파일에 둔다. 파일에서 리소스를 빼면 삭제 계획이 만들어질 수 있으므로 `railway config apply` 전에 destroy 항목을 반드시 확인한다. 생성형 Railway domain과 `GITHUB_TOKEN`의 실제 값은 repository에 저장하지 않는다. domain은 최초 적용 후 별도로 만들고, token은 environment별 shared variable로 먼저 만든다.

## 최초 staging 적용 순서

1. 이 변경을 `main`에 commit/push한다. IaC가 가리키는 source는 `g-seo/Repovil`의 `main`이고 Dockerfile도 같은 commit에 있어야 한다.
2. Railway dashboard에서 project를 준비한다. GitHub 계정만 연결했다면 빈 project `Repovil`을 만든다. `Deploy from GitHub`로 이미 service가 생겼다면 service 이름을 `repovil-api`로 바꾸고, 불필요한 데이터를 넣지 않는다.
3. Railway CLI 5.42.1 이상을 설치하고 `railway login`, `railway link`로 이 project를 연결한다. repository root에서 `railway status`로 project 이름을 확인한다.
4. `railway environment new staging`으로 빈 staging environment를 만들고 `railway environment staging`으로 전환한다. 이후 모든 plan/apply 출력에서 environment가 `staging`인지 확인한다.
5. Dashboard의 `Project Settings → Shared Variables`에서 environment를 `staging`으로 선택하고 `GITHUB_TOKEN`을 추가한다. 최소 권한의 staging용 fine-grained token을 사용한다. IaC의 `ctx.shared.GITHUB_TOKEN`은 이 값을 참조할 뿐 생성하지 않는다.
6. `npm ci`, `npm run iac:check`, `npm run iac:test`를 실행한다.
7. `railway config plan`을 실행한다. 새 빈 staging이면 `Postgres`, `repovil-api`, `repovil-web`, `repovil-daily`, `repovil-tracking` 다섯 리소스 생성이 보여야 한다. 예상하지 않은 변경이나 destroy가 하나라도 있으면 apply하지 않는다.
8. plan이 정확할 때만 `railway config apply`를 실행하고 대화형 확인에 승인한다. 최초 적용에는 과금 가능한 PostgreSQL과 service가 생성된다.
9. 배포가 모두 성공한 뒤 public staging domain을 만든다.

   ```bash
   railway domain --service repovil-web --environment staging
   railway domain --service repovil-api --environment staging --port 8000
   ```

10. 아래 smoke checklist를 실행한다. 첫 daily/tracking 예약 실행으로 UTC schedule 기동을 확인한다. 이후 worker-only 수정은 같은 배포 image, start command, variable을 사용하는 Railway `Run now`로 즉시 재검증할 수 있으며, 변경하지 않은 schedule을 다시 기다리지 않는다.

production은 staging 검증과 backup/PITR 확인이 끝난 뒤 별도 plan/apply한다. staging의 shared secret은 production으로 자동 복사되지 않으므로 production `GITHUB_TOKEN`도 별도로 등록한다.

## 환경 변수와 network

Railway variable 또는 reference variable로만 값을 주입한다. repository, image layer, build argument, log에는 실제 값을 넣지 않는다.

| Service | 필수 variable |
|---|---|
| API | `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `PORT=8000` |
| Web | `REPOVIL_API_URL=http://${{repovil-api.RAILWAY_PRIVATE_DOMAIN}}:8000` |
| Daily / Tracking | `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `GITHUB_TOKEN`, `GITHUB_API_VERSION=2026-03-10` |

선택 worker 설정은 `GITHUB_API_TIMEOUT_SECONDS`, `GITHUB_API_MAX_RETRIES`다. API와 web에는 GitHub token을 주입하지 않는다. `repovil-deploy-check`와 web startup script는 필수 variable이 없거나 공백이면 이름만 JSON log에 남기고 non-zero로 종료한다. 값은 출력하지 않는다.

API port는 private reference를 안정적으로 조합하기 위해 IaC에서 `8000`으로 고정한다. Web은 Railway가 제공하는 `PORT`를 사용한다. Web의 server-side fetch에는 private domain을 사용한다.

## Release와 migration

1. PostgreSQL backup/PITR 상태와 새 migration의 forward/backward smoke 결과를 확인한다.
2. IaC는 프로젝트 전체를 함께 적용하므로 다음 cron slot 직전에는 release하지 않는다. API migration과 readiness를 확인할 시간이 충분한 slot 직후에 plan/apply한다.
3. API pre-deploy는 `repovil-deploy-check api`, `alembic upgrade head`, `repovil-sync-categories` 순서로 실행된다. 실패하면 새 API process가 시작되지 않는다. 로그를 확인하고 원인을 수정하며 production DB에서 임의 downgrade하지 않는다.
   Dockerfile 기반 service의 custom command는 exec form으로 실행되므로, 여러 명령을 연결하는 API와 Cron command는 IaC에서 명시적으로 `/bin/sh -c`로 감싼다.
4. Worker image도 함께 build될 수 있지만 cron process는 예약 시각에만 시작한다. 새 migration은 직전 application image와도 호환되게 작성해 build/deploy 경합 중 schema 호환성을 유지한다.
5. 다음 cron slot 전에 `/health`가 HTTP 200인지 확인하고 `/ready`가 DB 연결을 포함해 HTTP 200인지 확인한다. Railway deployment healthcheck는 `/ready`다.
6. Web page와 worker variable 설정을 확인하고, 첫 cron 실행의 JSON log와 종료 상태를 관찰한다.

애플리케이션 rollback은 이전 image를 redeploy하되 migration과 호환되는 version만 선택한다. schema/data rollback이 필요하면 배포를 중단하고 승인된 backup 복구 절차를 사용한다. production에서 `alembic downgrade`를 즉흥 실행하지 않는다.

## 로그와 실패 판정

Worker 로그는 한 줄 JSON이며 event에 적용 가능한 `run_id`, `repository_id`, `response_status`, `retry_count`, `duration_ms`를 포함한다. `discovery_run_finished`, `tracking_run_finished`, `*_repository_failed`를 run id로 묶어 조회한다. token과 DB URL은 허용된 구조화 필드가 아니므로 formatter가 출력하지 않는다.

- Discovery가 `PARTIAL`/`FAILED`, bootstrap에 repository 실패가 하나 이상, tracking이 `PARTIAL`/`FAILED`이면 cron은 non-zero로 종료한다.
- Tracking `PARTIAL`이 95% publication 기준을 만족하면 ranking은 원자적으로 공개될 수 있지만 cron은 실패 repository가 있었음을 알리기 위해 여전히 non-zero다.
- Tracking 성공률이 95% 미만이거나 분모가 0이면 `published_at`을 설정하지 않고 직전 공개 ranking을 유지한다.

## 안전한 수동 재실행

먼저 DB와 JSON log에서 정확한 run id/status를 확인한다. 같은 worker를 동시에 여러 번 시작하지 않는다.

```sql
SELECT id, status, started_at, finished_at, failed_ranges
FROM discovery_runs
ORDER BY id DESC
LIMIT 20;

SELECT id, scheduled_at, status, success_count, failed_count,
       skipped_count, published_at
FROM tracking_runs
ORDER BY scheduled_at DESC
LIMIT 20;
```

- Discovery: 실패 구간만 새 run으로 재처리하려면 `repovil-discovery --retry-run RUN_ID`를 한 번 실행한다. 원 run과 원천 history는 유지된다.
- Bootstrap: `repovil-bootstrap`을 다시 실행한다. `bootstrap_pending`만 대상으로 하고 이미 저장한 원천 row는 덮어쓰지 않는다.
- Tracking: `repovil-tracking --scheduled-at YYYY-MM-DDTHH:00:00Z`는 00/06/12/18 UTC slot만 허용한다. 이미 끝난 slot은 snapshot을 중복 수집하지 않고 필요한 ranking publication만 재시도한다. 이미 공개된 run을 변경하지 않는다. 새 측정이 필요하면 다음 UTC slot을 실행한다.
- 동시 실행 오류는 advisory lock이 정상 동작한 것이므로 기존 실행의 종료를 확인한 뒤 한 번만 재실행한다.

### Worker 수정 직후 staging 재검증

UTC schedule 기동이 실제 예약 실행으로 이미 확인됐고 cron schedule/IaC를 변경하지 않았다면 다음 예약 시각까지 기다리지 않는다. Railway Dashboard의 해당 service `Cron Runs`에서 `Run now`를 사용한다. `railway cron run`을 지원하는 CLI에서는 `railway cron run --service SERVICE --environment staging --yes`도 같은 용도이며, 지원하지 않는 CLI에서는 Dashboard를 사용한다.

1. 실행 중인 같은 worker가 없는지 확인한다.
2. `repovil-tracking`을 `Run now`로 실행한다. 현재 slot의 완료 run이 미공개 상태라면 기존 run을 불러 publication만 재시도하며 snapshot을 다시 수집하지 않아야 한다.
3. Railway run이 `EXITED`인지, 기존 run의 `published_at`과 ranking row가 새 DB connection에서도 보존되는지, API가 해당 `tracking_run_id`를 반환하는지 확인한다.
4. `repovil-daily`를 `Run now`로 실행한다. discovery의 `github_id` 중복 방지와 bootstrap의 `bootstrap_pending` 선택으로 기존 성공 데이터를 덮어쓰지 않아야 한다.
5. rate limit 발생 시 `github_request_retry_scheduled`의 resource/reset/sleep을 확인하고, reset 경계 이후 작업이 계속되어 최종 run과 process가 성공하는지 확인한다.

이 즉시 실행은 worker 동작과 Railway 종료 상태 검증을 대체한다. UTC schedule 기동 증거가 아직 한 번도 없다면 최초 실제 예약 실행 확인은 별도로 필요하다. 검증을 위해 cron schedule을 임시로 변경하지 않는다.

## Smoke checklist

Staging에서 production과 같은 image와 start command로 다음을 확인한다.

1. 빈 격리 DB에서 API pre-deploy를 실행하고 category sync를 두 번 실행해 idempotency를 확인한다.
2. API `/health`와 `/ready`, web `/`가 HTTP 200인지 확인한다. DB 연결을 잠시 잘못 지정한 staging service에서 `/ready`가 503인지 확인하고 즉시 복구한다.
3. 동일 tracking slot을 동시에 실행해 한 실행만 lock을 획득하고 중복 snapshot이 없는지 확인한다.
4. fixture/staging token으로 일부 GitHub 요청을 실패시켜 non-zero exit, JSON failure log, DB `PARTIAL`, 95% 정책에 따른 직전 ranking 보존 또는 원자적 공개를 확인한다.
5. 필수 variable 하나를 제거한 임시 staging deployment가 값 노출 없이 시작을 거부하는지 확인한다.

실제 production data 변경, deploy, destructive rollback은 별도 승인을 받은 뒤 수행한다.

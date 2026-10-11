import {
  defineRailway,
  github,
  postgres,
  service,
  type BuildConfig,
} from "railway/iac";

const repository = "g-seo/Repovil";
const branch = "main";

function backendBuild(watchPatterns: string[]): BuildConfig {
  return {
    builder: "DOCKERFILE",
    dockerfilePath: "deploy/Dockerfile.backend",
    watchPatterns,
  };
}

export default defineRailway((ctx, project) => {
  const source = () => github(repository, { branch });
  const database = postgres("Postgres");

  const api = service("repovil-api", {
    source: source(),
    build: backendBuild([
      "backend/**",
      "alembic/**",
      "config/**",
      "pyproject.toml",
      "uv.lock",
      "alembic.ini",
      "deploy/Dockerfile.backend",
      ".railway/railway.ts",
    ]),
    deploy: {
      preDeployCommand: [
        "repovil-deploy-check api && alembic upgrade head && repovil-sync-categories",
      ],
      startCommand: "repovil-deploy-check api && repovil-api",
      healthcheckPath: "/ready",
      healthcheckTimeout: 60,
      restartPolicyType: "ON_FAILURE",
      restartPolicyMaxRetries: 3,
    },
    env: {
      DATABASE_URL: database.env.DATABASE_URL,
      PORT: "8000",
    },
  });

  const web = service("repovil-web", {
    source: source(),
    build: {
      builder: "DOCKERFILE",
      dockerfilePath: "deploy/Dockerfile.frontend",
      watchPatterns: [
        "frontend/**",
        "deploy/Dockerfile.frontend",
        "deploy/start-web.sh",
        ".railway/railway.ts",
      ],
    },
    deploy: {
      startCommand: "/bin/sh /app/start-web.sh",
      healthcheckPath: "/",
      healthcheckTimeout: 60,
      restartPolicyType: "ON_FAILURE",
      restartPolicyMaxRetries: 3,
    },
    env: {
      REPOVIL_API_URL:
        "http://${{repovil-api.RAILWAY_PRIVATE_DOMAIN}}:8000",
    },
  });

  const daily = service("repovil-daily", {
    source: source(),
    build: backendBuild([
      "backend/**",
      "config/**",
      "pyproject.toml",
      "uv.lock",
      "deploy/Dockerfile.backend",
      ".railway/railway.ts",
    ]),
    deploy: {
      startCommand: "repovil-deploy-check worker && repovil-daily",
      cronSchedule: "0 3 * * *",
      restartPolicyType: "NEVER",
    },
    env: {
      DATABASE_URL: database.env.DATABASE_URL,
      GITHUB_TOKEN: ctx.shared.GITHUB_TOKEN,
      GITHUB_API_VERSION: "2026-03-10",
    },
  });

  const tracking = service("repovil-tracking", {
    source: source(),
    build: backendBuild([
      "backend/**",
      "config/**",
      "pyproject.toml",
      "uv.lock",
      "deploy/Dockerfile.backend",
      ".railway/railway.ts",
    ]),
    deploy: {
      startCommand: "repovil-deploy-check worker && repovil-tracking",
      cronSchedule: "0 */6 * * *",
      restartPolicyType: "NEVER",
    },
    env: {
      DATABASE_URL: database.env.DATABASE_URL,
      GITHUB_TOKEN: ctx.shared.GITHUB_TOKEN,
      GITHUB_API_VERSION: "2026-03-10",
    },
  });

  return project(ctx.projectName ?? "Repovil", {
    resources: [database, api, web, daily, tracking],
  });
});

import assert from "node:assert/strict";
import test from "node:test";

import { createRailwayContext, project } from "railway/iac";

import configuration from "./railway.ts";

async function resourcesByName() {
  const definition = await configuration(
    createRailwayContext({ environment: "staging", projectName: "Repovil" }),
    project,
  );

  return new Map(definition.resources.map((resource) => [resource.name, resource]));
}

test("IaC defines the complete Repovil project", async () => {
  const resources = await resourcesByName();

  assert.deepEqual([...resources.keys()], [
    "Postgres",
    "repovil-api",
    "repovil-web",
    "repovil-daily",
    "repovil-tracking",
  ]);

  for (const name of [
    "repovil-api",
    "repovil-web",
    "repovil-daily",
    "repovil-tracking",
  ]) {
    assert.deepEqual(resources.get(name).source, {
      type: "github",
      repo: "g-seo/Repovil",
      branch: "main",
    });
  }
});

test("services use private references and the migration-first release command", async () => {
  const resources = await resourcesByName();
  const api = resources.get("repovil-api");
  const web = resources.get("repovil-web");

  assert.equal(api.deploy.healthcheckPath, "/ready");
  assert.match(api.deploy.preDeployCommand[0], /alembic upgrade head/);
  assert.deepEqual(api.variables.DATABASE_URL, {
    type: "reference",
    resource: "database.Postgres",
    output: "DATABASE_URL",
  });
  assert.deepEqual(api.variables.PORT, { type: "literal", value: "8000" });
  assert.deepEqual(web.variables.REPOVIL_API_URL, {
    type: "literal",
    value: "http://${{repovil-api.RAILWAY_PRIVATE_DOMAIN}}:8000",
  });
});

test("workers share the GitHub secret and keep UTC cron schedules", async () => {
  const resources = await resourcesByName();
  const daily = resources.get("repovil-daily");
  const tracking = resources.get("repovil-tracking");

  assert.equal(daily.kind, "github");
  assert.equal(daily.deploy.cronSchedule, "0 3 * * *");
  assert.equal(daily.deploy.restartPolicyType, "NEVER");
  assert.equal(tracking.kind, "github");
  assert.equal(tracking.deploy.cronSchedule, "0 */6 * * *");
  assert.equal(tracking.deploy.restartPolicyType, "NEVER");

  for (const worker of [daily, tracking]) {
    assert.deepEqual(worker.variables.GITHUB_TOKEN, {
      type: "sharedReference",
      name: "GITHUB_TOKEN",
    });
    assert.deepEqual(worker.variables.DATABASE_URL, {
      type: "reference",
      resource: "database.Postgres",
      output: "DATABASE_URL",
    });
  }
});

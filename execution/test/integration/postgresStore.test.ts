import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import pg from "pg";
import { afterAll, describe, expect, it } from "vitest";
import { PostgresStore, migrate } from "../../src/store/PostgresStore.js";
import { storeContract } from "../helpers/storeContract.js";
import { T0 } from "../helpers/fixtures.js";

/**
 * Runs against a real PostgreSQL when TEST_DATABASE_URL is set (CI, docker compose, local initdb).
 * Each test gets its own schema so runs are independent. Skipped (and reported as skipped) otherwise.
 */
const url = process.env.TEST_DATABASE_URL;
const migrations = fileURLToPath(new URL("../../db/migrations", import.meta.url));
const pools: pg.Pool[] = [];

async function fresh(): Promise<{ store: PostgresStore; pool: pg.Pool }> {
  const schema = `t_${randomUUID().replaceAll("-", "")}`;
  const admin = new pg.Pool({ connectionString: url });
  await admin.query(`CREATE SCHEMA ${schema}`);
  await admin.end();
  const pool = new pg.Pool({ connectionString: url, options: `-c search_path=${schema}` });
  pools.push(pool);
  await migrate(pool, migrations);
  return { store: new PostgresStore(pool), pool };
}

describe.skipIf(!url)("PostgreSQL", () => {
  afterAll(async () => {
    await Promise.all(pools.map((p) => p.end()));
  });

  storeContract("postgres", async () => (await fresh()).store);

  it("refuses UPDATE, DELETE and TRUNCATE on the audit trail", async () => {
    const { store, pool } = await fresh();
    await store.appendAudit({ at: T0.toISOString(), tradeId: null, type: "X", payload: {} });
    await expect(pool.query("UPDATE audit_events SET type = 'Y'")).rejects.toThrow(/append-only/);
    await expect(pool.query("DELETE FROM audit_events")).rejects.toThrow(/append-only/);
    await expect(pool.query("TRUNCATE audit_events")).rejects.toThrow(/append-only/);
  });

  it("refuses to re-decide an approval at the database level", async () => {
    const { store, pool } = await fresh();
    const { trade } = await import("../helpers/storeContract.js");
    await store.insertTrade(trade("t"));
    await store.insertApproval({ approvalId: "a", tradeId: "t", intentHash: "a".repeat(64), nonceHash: "b".repeat(64), status: "PENDING", expiresAt: T0.toISOString(), createdAt: T0.toISOString() });
    await store.decideApproval("a", "DENIED", "1", T0.toISOString());
    await expect(pool.query("UPDATE approvals SET status = 'APPROVED' WHERE approval_id = 'a'")).rejects.toThrow(/single use/);
  });

  it("migrations are idempotent", async () => {
    const { pool } = await fresh();
    expect(await migrate(pool, migrations)).toEqual([]);
  });
});

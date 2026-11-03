import { expect, it } from "vitest";
import { verifyChain } from "../../src/audit/hash.js";
import { MemoryStore } from "../../src/store/MemoryStore.js";
import { storeContract } from "../helpers/storeContract.js";
import { T0 } from "../helpers/fixtures.js";

storeContract("memory", async () => new MemoryStore());

it("detects tampering with the audit chain", async () => {
  const s = new MemoryStore();
  for (let i = 0; i < 3; i++) await s.appendAudit({ at: T0.toISOString(), tradeId: null, type: "X", payload: { i } });
  expect(verifyChain(await s.listAudit()).ok).toBe(true);
  s._auditForTest()[1]!.payload = { i: 99 };
  expect(verifyChain(s._auditForTest())).toEqual({ ok: false, brokenAtSeq: 2 });
});

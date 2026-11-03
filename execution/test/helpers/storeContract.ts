import { describe, expect, it } from "vitest";
import { verifyChain } from "../../src/audit/hash.js";
import type { TradeRecord } from "../../src/domain/types.js";
import type { Store } from "../../src/store/Store.js";
import { DAY, T0, proposal } from "./fixtures.js";

export function trade(id: string, over: Partial<TradeRecord> = {}): TradeRecord {
  return {
    tradeId: id,
    mode: "PAPER",
    tradingDay: DAY,
    proposal: proposal(),
    state: "PROPOSED",
    risk: null,
    entryClientRef: `E${id}`,
    filledQuantity: 0,
    confirmedPositionQuantity: 0,
    protectedQuantity: 0,
    ocoAttempts: 0,
    flags: {},
    version: 1,
    createdAt: T0.toISOString(),
    updatedAt: T0.toISOString(),
    ...over,
  };
}

/** The same behavioural contract for every Store implementation. */
export function storeContract(name: string, make: () => Promise<Store>) {
  describe(`${name} store contract`, () => {
    it("allows exactly one trade per mode per trading day", async () => {
      const s = await make();
      expect(await s.claimDailySlot("PAPER", DAY, "a")).toBe(true);
      expect(await s.claimDailySlot("PAPER", DAY, "b")).toBe(false);
      expect(await s.dailySlotHolder("PAPER", DAY)).toBe("a");
      expect(await s.claimDailySlot("LIVE_APPROVAL", DAY, "c")).toBe(true);
      const [x, y] = await Promise.all([s.claimDailySlot("PAPER", "2026-11-05", "p"), s.claimDailySlot("PAPER", "2026-11-05", "q")]);
      expect([x, y].filter(Boolean)).toHaveLength(1);
    });

    it("saves trades with optimistic concurrency", async () => {
      const s = await make();
      const t = trade("t1");
      await s.insertTrade(t);
      await s.saveTrade({ ...t, state: "AWAITING_APPROVAL", version: 2 });
      await expect(s.saveTrade({ ...t, state: "RISK_REJECTED", version: 2 })).rejects.toThrow(/version/);
      expect((await s.getTrade("t1"))?.state).toBe("AWAITING_APPROVAL");
      expect((await s.listOpenTrades("PAPER")).map((x) => x.tradeId)).toContain("t1");
    });

    it("decides an approval exactly once, even under a race", async () => {
      const s = await make();
      await s.insertTrade(trade("t2"));
      await s.insertApproval({
        approvalId: "ap1",
        tradeId: "t2",
        kind: "ENTRY",
        intentHash: "a".repeat(64),
        nonceHash: "b".repeat(64),
        status: "PENDING",
        expiresAt: new Date(T0.getTime() + 90_000).toISOString(),
        createdAt: T0.toISOString(),
      });
      const results = await Promise.all([
        s.decideApproval("ap1", "APPROVED", "1", T0.toISOString()),
        s.decideApproval("ap1", "APPROVED", "1", T0.toISOString()),
        s.decideApproval("ap1", "DENIED", "1", T0.toISOString()),
      ]);
      expect(results.filter((r) => r !== null)).toHaveLength(1);
      expect(await s.decideApproval("ap1", "APPROVED", "1", T0.toISOString())).toBeNull();
      await s.setApprovalMessageId("ap1", 42);
      expect((await s.getApproval("ap1"))?.telegramMessageId).toBe(42);
    });

    it("keeps a verifiable, redacted, hash-chained audit trail", async () => {
      const s = await make();
      await s.appendAudit({ at: T0.toISOString(), tradeId: "t3", type: "A", payload: { n: 1, apiKey: "should-not-appear" } });
      await s.appendAudit({ at: T0.toISOString(), tradeId: null, type: "B", payload: { nested: { access_token: "x" }, ok: true } });
      const all = await s.listAudit();
      expect(verifyChain(all).ok).toBe(true);
      expect(JSON.stringify(all)).not.toContain("should-not-appear");
      expect(all[0]!.payload.apiKey).toBe("[REDACTED]");
      expect(await s.listAudit("t3")).toHaveLength(1);
    });

    it("counts paper track record and open safety incidents", async () => {
      const s = await make();
      await s.insertTrade(trade("t4", { state: "CLOSED" }));
      await s.appendAudit({ at: T0.toISOString(), tradeId: "t4", type: "PROTECTION_CONFIRMED", payload: {} });
      await s.appendAudit({ at: T0.toISOString(), tradeId: null, type: "SAFETY_INCIDENT", payload: { incidentId: "i1" } });
      expect(await s.paperTrackRecord()).toEqual({ completedWorkflows: 1, safetyIncidents: 1 });
      await s.appendAudit({ at: T0.toISOString(), tradeId: null, type: "SAFETY_INCIDENT_RESOLVED", payload: { incidentId: "i1" } });
      expect((await s.paperTrackRecord()).safetyIncidents).toBe(0);
    });

    it("stores key/value state", async () => {
      const s = await make();
      expect(await s.getKv("k")).toBeNull();
      await s.setKv("k", "1");
      await s.setKv("k", "2");
      expect(await s.getKv("k")).toBe("2");
    });
  });
}

import { describe, expect, it } from "vitest";
import { verifyChain } from "../../src/audit/hash.js";
import { HALT_KEY } from "../../src/engine/TradeOps.js";
import { CHAT, OWNER, harness } from "../helpers/harness.js";

describe("PAPER workflow end to end", () => {
  it("proposal -> approval -> accepted (not filled) -> fill -> OCO confirmed -> target -> closed", async () => {
    const h = harness();
    let t = await h.propose();
    expect(t.state).toBe("AWAITING_APPROVAL");
    expect(h.notifier.approvals).toHaveLength(1);
    expect(h.notifier.approvals[0]!.text).toMatch(/PAPER order approval/);
    expect(await h.broker.findOrderByClientRef(t.entryClientRef, "CASH")).toBeNull(); // nothing sent before approval

    await h.press("approve");
    t = await h.trade(t.tradeId);
    expect(t.state).toBe("ENTRY_PENDING"); // accepted is not filled
    expect(t.filledQuantity).toBe(0);
    expect(h.notifier.alerts.join()).toMatch(/Not filled yet/);

    h.broker.tick(h.sym, 1000.5); // above the limit: no fill
    await h.run();
    t = await h.trade(t.tradeId);
    expect(t.state).toBe("ENTRY_PENDING");
    expect(t.protectedQuantity).toBe(0);

    h.broker.tick(h.sym, 999.95); // fill
    await h.run(); // fills seen, OCO submitted
    t = await h.trade(t.tradeId);
    expect(t.filledQuantity).toBe(12);
    expect(t.state).toBe("PROTECTION_PENDING"); // submitted, not yet confirmed
    await h.run(); // OCO confirmed ACTIVE
    t = await h.trade(t.tradeId);
    expect(t.state).toBe("PROTECTED");
    expect(t.protectedQuantity).toBe(12);

    h.broker.tick(h.sym, 1040);
    await h.run();
    t = await h.trade(t.tradeId);
    expect(t.state).toBe("CLOSED");
    expect(t.closeReason).toMatch(/TARGET/);
    expect(t.realisedPnlInr).toBeGreaterThan(0);

    const audit = await h.store.listAudit();
    expect(verifyChain(audit).ok).toBe(true);
    const types = audit.map((e) => e.type);
    expect(types.indexOf("APPROVAL_GRANTED")).toBeLessThan(types.findIndex((x, i) => x === "STATE" && audit[i]!.payload.to === "ENTRY_SUBMITTING"));
    expect(types).toContain("PROTECTION_CONFIRMED");
    expect(await h.store.paperTrackRecord()).toEqual({ completedWorkflows: 1, safetyIncidents: 0 });
  });

  it("stop-loss leg closes the trade with a loss", async () => {
    const h = harness();
    const t0 = await h.propose();
    await h.press("approve");
    h.broker.tick(h.sym, 999.9);
    await h.run(2);
    h.broker.tick(h.sym, 989.5);
    await h.run();
    const t = await h.trade(t0.tradeId);
    expect(t.state).toBe("CLOSED");
    expect(t.closeReason).toMatch(/STOP/);
    expect(t.realisedPnlInr).toBeLessThan(0);
    expect(Math.abs(t.realisedPnlInr!)).toBeLessThanOrEqual(300);
  });

  describe("approval gateway", () => {
    it("sends nothing without approval and expires the request", async () => {
      const h = harness();
      const t0 = await h.propose();
      h.clock.advance((h.cfg.approvalTtlSec + 1) * 1000);
      await h.run();
      expect((await h.trade(t0.tradeId)).state).toBe("APPROVAL_EXPIRED");
      expect(await h.broker.findOrderByClientRef(t0.entryClientRef, "CASH")).toBeNull();
      await h.press("approve"); // late press does nothing
      expect(await h.broker.findOrderByClientRef(t0.entryClientRef, "CASH")).toBeNull();
    });

    it("reject sends nothing", async () => {
      const h = harness();
      const t0 = await h.propose();
      await h.press("reject");
      expect((await h.trade(t0.tradeId)).state).toBe("APPROVAL_DENIED");
      expect(await h.broker.findOrderByClientRef(t0.entryClientRef, "CASH")).toBeNull();
    });

    it("ignores other users and other chats", async () => {
      const h = harness();
      const t0 = await h.propose();
      await h.press("approve", -1, 999, CHAT);
      await h.press("approve", -1, OWNER, 555);
      expect((await h.trade(t0.tradeId)).state).toBe("AWAITING_APPROVAL");
      const types = (await h.store.listAudit()).map((e) => e.type);
      expect(types.filter((x) => x === "APPROVAL_UNAUTHORIZED")).toHaveLength(2);
    });

    it("is single use: a double tap sends one order", async () => {
      const h = harness();
      const t0 = await h.propose();
      await Promise.all([h.press("approve"), h.press("approve")]);
      await h.press("approve");
      const grants = (await h.store.listAudit(t0.tradeId)).filter((e) => e.type === "APPROVAL_GRANTED");
      expect(grants).toHaveLength(1);
      expect((await h.trade(t0.tradeId)).state).toBe("ENTRY_PENDING");
    });

    it("rejects a forged nonce", async () => {
      const h = harness();
      const t0 = await h.propose();
      const a = h.notifier.approvals[0]!;
      const forged = a.buttons.approveData.replace(/\|[^|]+$/, "|AAAAAAAAAAAAAAAAAAAAAA");
      await h.svc.handleCallback({ callbackQueryId: "x", fromUserId: OWNER, chatId: CHAT, data: forged, messageId: a.messageId });
      expect((await h.trade(t0.tradeId)).state).toBe("AWAITING_APPROVAL");
    });

    it("voids the approval if the order changed after the request", async () => {
      const h = harness();
      const t0 = await h.propose();
      const cur = await h.trade(t0.tradeId);
      await h.store.saveTrade({ ...cur, proposal: { ...cur.proposal, quantity: 20 }, version: cur.version + 1 });
      await h.press("approve");
      const t = await h.trade(t0.tradeId);
      expect(t.state).toBe("APPROVAL_EXPIRED");
      expect(await h.broker.findOrderByClientRef(t.entryClientRef, "CASH")).toBeNull();
    });

    it("re-checks risk with a fresh quote after approval", async () => {
      const h = harness();
      const t0 = await h.propose();
      h.broker.tick(h.sym, 1015); // price ran 1.5% away while the owner read the message
      await h.press("approve");
      const t = await h.trade(t0.tradeId);
      expect(t.state).toBe("RISK_REJECTED");
      expect(t.risk!.reasons.join()).toMatch(/from the last price/);
      expect(await h.broker.findOrderByClientRef(t.entryClientRef, "CASH")).toBeNull();
    });
  });

  describe("risk limits in the workflow", () => {
    it("allows only one trade per day, even after a rejection", async () => {
      const h = harness();
      const a = await h.propose();
      await h.press("reject");
      expect((await h.trade(a.tradeId)).state).toBe("APPROVAL_DENIED");
      const b = await h.propose({ proposalId: "prop-2" });
      expect(b.state).toBe("RISK_REJECTED");
      expect(b.risk!.reasons.join()).toMatch(/one trade/);
      expect(h.notifier.approvals).toHaveLength(1);
    });

    it("rejects a proposal over ₹300 planned risk without asking for approval", async () => {
      const h = harness({}, { MAX_NOTIONAL_INR: "100000" });
      const t = await h.propose({ quantity: 40 });
      expect(t.state).toBe("RISK_REJECTED");
      expect(h.notifier.approvals).toHaveLength(0);
      expect(h.notifier.alerts.join()).toMatch(/NO TRADE/);
    });
  });

  describe("partial fills", () => {
    it("protects each confirmed fill and resizes the OCO to the full position", async () => {
      const h = harness({ entryFillSizes: [5, 7] });
      const t0 = await h.propose();
      await h.press("approve");
      h.broker.tick(h.sym, 999.9);
      await h.run(2);
      let t = await h.trade(t0.tradeId);
      expect(t.filledQuantity).toBe(5);
      expect(t.state).toBe("PROTECTED");
      expect(t.protectedQuantity).toBe(5);

      h.broker.tick(h.sym, 999.8); // rest fills
      await h.run(); // sees 12, resizes OCO
      t = await h.trade(t0.tradeId);
      expect(t.filledQuantity).toBe(12);
      expect(t.state).toBe("PROTECTION_PENDING");
      await h.run();
      t = await h.trade(t0.tradeId);
      expect(t.state).toBe("PROTECTED");
      expect(t.protectedQuantity).toBe(12);
    });

    it("cancels the unfilled remainder at the end of the entry window", async () => {
      const h = harness({ entryFillSizes: [5] });
      const t0 = await h.propose();
      await h.press("approve");
      h.broker.tick(h.sym, 999.9);
      await h.run(2);
      h.clock.set("2026-11-04T09:01:00Z"); // 14:31 IST
      await h.run();
      const order = await h.broker.findOrderByClientRef(t0.entryClientRef, "CASH");
      expect(order!.status).toBe("CANCELLED");
      expect((await h.trade(t0.tradeId)).protectedQuantity).toBe(5);
    });

    it("ends as ENTRY_CANCELLED when nothing fills by the window end", async () => {
      const h = harness();
      const t0 = await h.propose();
      await h.press("approve");
      h.clock.set("2026-11-04T09:01:00Z");
      await h.run(2);
      expect((await h.trade(t0.tradeId)).state).toBe("ENTRY_CANCELLED");
    });
  });

  describe("OCO failures", () => {
    it("retries a rejected OCO and confirms the replacement", async () => {
      const h = harness({ ocoSubmitRejections: 1 });
      const t0 = await h.propose();
      await h.press("approve");
      h.broker.tick(h.sym, 999.9);
      await h.run(3);
      const t = await h.trade(t0.tradeId);
      expect(t.state).toBe("PROTECTED");
      expect(t.ocoAttempts).toBe(2);
    });

    it("after exhausted retries: PROTECTION_FAILED, incident, halt, and an EXIT approval (never an automatic exit)", async () => {
      const h = harness({ ocoSubmitRejections: 10 });
      const t0 = await h.propose();
      await h.press("approve");
      h.broker.tick(h.sym, 999.9);
      await h.run(4);
      let t = await h.trade(t0.tradeId);
      expect(t.state).toBe("PROTECTION_FAILED");
      expect(t.protectedQuantity).toBe(0);
      expect(await h.store.getKv(HALT_KEY)).not.toBeNull();
      expect(h.notifier.alerts.join()).toMatch(/NOT protected/);
      expect(h.notifier.approvals.at(-1)!.text).toMatch(/exit approval/i);
      expect((await h.broker.getPosition(h.sym, "CASH")).netQuantity).toBe(12); // nothing sold without approval

      await h.press("approve"); // owner approves the exit
      t = await h.trade(t0.tradeId);
      expect(t.state).toBe("EXIT_PENDING");
      h.broker.tick(h.sym, 999);
      await h.run();
      t = await h.trade(t0.tradeId);
      expect(t.state).toBe("CLOSED");
      expect((await h.broker.getPosition(h.sym, "CASH")).netQuantity).toBe(0);
    });

    it("treats a REJECTED/FAILED OCO status as unprotected", async () => {
      const h = harness({ ocoOutcome: "FAILED" });
      const t0 = await h.propose();
      await h.press("approve");
      h.broker.tick(h.sym, 999.9);
      for (let i = 0; i < 8; i++) await h.run();
      const t = await h.trade(t0.tradeId);
      expect(t.state).toBe("PROTECTION_FAILED");
      expect((await h.store.listAudit(t0.tradeId)).some((e) => e.type === "PROTECTION_CONFIRMED")).toBe(false);
    });

    it("resolves a lost OCO response by reference without creating a duplicate", async () => {
      const h = harness({ ocoSubmitTimeouts: 1 });
      const t0 = await h.propose();
      await h.press("approve");
      h.broker.tick(h.sym, 999.9);
      await h.run(3);
      const t = await h.trade(t0.tradeId);
      expect(t.state).toBe("PROTECTED");
      expect(t.ocoAttempts).toBe(1);
      expect((await h.store.listAudit(t0.tradeId)).some((e) => e.type === "OCO_FOUND_BY_REF")).toBe(true);
    });

    it("cancels an OCO stuck in PENDING past the timeout and replaces it", async () => {
      const h = harness({ ocoActivationDelay: 1000 });
      const t0 = await h.propose();
      await h.press("approve");
      h.broker.tick(h.sym, 999.9);
      await h.run(2);
      h.clock.advance((h.cfg.oco.confirmTimeoutSec + 1) * 1000);
      await h.run();
      const t = await h.trade(t0.tradeId);
      expect(t.ocoAttempts).toBe(2);
      expect(t.state).toBe("PROTECTION_PENDING");
      expect((await h.store.listAudit(t0.tradeId)).some((e) => e.type === "OCO_ATTEMPT_FAILED")).toBe(true);
    });
  });

  describe("entry failures and network interruptions", () => {
    it("never resubmits after a lost entry response; finds the order by reference", async () => {
      const h = harness({ entryTimeoutAfterAccept: true });
      const t0 = await h.propose();
      await h.press("approve");
      let t = await h.trade(t0.tradeId);
      expect(t.state).toBe("ENTRY_UNCERTAIN");
      await h.run();
      t = await h.trade(t0.tradeId);
      expect(t.state).toBe("ENTRY_PENDING");
      expect(t.entryOrderId).toBeDefined();
      const submits = (await h.store.listAudit(t0.tradeId)).filter((e) => e.type === "STATE" && e.payload.to === "ENTRY_SUBMITTING");
      expect(submits).toHaveLength(1);
    });

    it("records a broker rejection", async () => {
      const h = harness({ rejectEntry: "insufficient funds" });
      const t0 = await h.propose();
      await h.press("approve");
      expect((await h.trade(t0.tradeId)).state).toBe("ENTRY_REJECTED");
    });

    it("keeps working when Telegram alerts fail", async () => {
      const h = harness();
      const t0 = await h.propose();
      await h.press("approve");
      h.notifier.failAlerts = true;
      h.broker.tick(h.sym, 999.9);
      await h.run(2);
      expect((await h.trade(t0.tradeId)).state).toBe("PROTECTED");
      expect((await h.store.listAudit()).some((e) => e.type === "ALERT_FAILED")).toBe(true);
    });
  });

  describe("reconciliation", () => {
    it("flags a position that does not match the fills, halts new entries, and protects the actual position", async () => {
      const h = harness();
      const t0 = await h.propose();
      await h.press("approve");
      h.broker.tick(h.sym, 999.9);
      await h.run(2);
      h.broker._setPositionForTest(h.sym, 15); // e.g. a manual buy in the app
      await h.run(2);
      const t = await h.trade(t0.tradeId);
      expect(await h.store.getKv(HALT_KEY)).not.toBeNull();
      expect(t.confirmedPositionQuantity).toBe(15);
      expect(t.protectedQuantity).toBe(15);
      expect((await h.store.paperTrackRecord()).safetyIncidents).toBe(1);
    });

    it("halts when the position is opposite to the trade", async () => {
      const h = harness();
      const t0 = await h.propose();
      await h.press("approve");
      h.broker.tick(h.sym, 999.9);
      await h.run(2);
      h.broker._setPositionForTest(h.sym, -3);
      await h.run();
      expect((await h.trade(t0.tradeId)).state).toBe("HALTED");
    });

    it("cancels a working OCO when the position was closed elsewhere", async () => {
      const h = harness();
      const t0 = await h.propose();
      await h.press("approve");
      h.broker.tick(h.sym, 999.9);
      await h.run(2);
      h.broker._setPositionForTest(h.sym, 0);
      await h.run();
      const t = await h.trade(t0.tradeId);
      expect(t.state).toBe("CLOSED");
      expect((await h.broker.getOco(t.ocoId!, "CASH")).status).toBe("CANCELLED");
    });

    it("asks (does not act) at square-off time for an open intraday position", async () => {
      const h = harness();
      const t0 = await h.propose();
      await h.press("approve");
      h.broker.tick(h.sym, 999.9);
      await h.run(2);
      h.clock.set("2026-11-04T09:36:00Z"); // 15:06 IST
      await h.run();
      expect(h.notifier.approvals.at(-1)!.text).toMatch(/square-off time/);
      expect((await h.broker.getPosition(h.sym, "CASH")).netQuantity).toBe(12);
      expect((await h.trade(t0.tradeId)).state).toBe("PROTECTED");
    });
  });

  it("/halt from the owner blocks new entries; other users cannot halt", async () => {
    const h = harness();
    await h.svc.handleCommand({ fromUserId: 999, chatId: CHAT, text: "/halt" });
    expect(await h.store.getKv(HALT_KEY)).toBeNull();
    await h.svc.handleCommand({ fromUserId: OWNER, chatId: CHAT, text: "/halt" });
    const t = await h.propose();
    expect(t.state).toBe("RISK_REJECTED");
    expect(t.risk!.reasons.join()).toMatch(/halted/);
  });
});

import { randomBytes } from "node:crypto";
import type { OcoRequest, OcoSnapshot, TradeRecord } from "../domain/types.js";
import { BrokerRejectedError, type BrokerPort } from "../broker/BrokerPort.js";
import type { TradeOps } from "./TradeOps.js";

export interface OcoPolicy {
  maxAttempts: number;
  confirmTimeoutSec: number;
}

/** 16-char alphanumeric reference (Groww's documented reference-id length is unverified; see UNVERIFIED.md). */
export function newRef(prefix: "E" | "O" | "X"): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = randomBytes(15);
  let s = prefix;
  for (const b of bytes) s += alphabet[b % alphabet.length];
  return s;
}

/**
 * Keeps a confirmed position covered by exactly one broker OCO (stop + target) whose quantity equals the
 * broker-confirmed position. One step per reconcile cycle; never blocks.
 *
 * Rules:
 *  - The request reference is saved BEFORE sending, so a crash or timeout can be resolved by lookup.
 *  - PROTECTED only after getOco() says ACTIVE and its quantity equals |position|.
 *  - A stuck PENDING OCO is cancelled before a replacement is sent (no double protection).
 *  - After maxAttempts the trade becomes PROTECTION_FAILED; the engine then raises a safety incident and
 *    asks the owner for a one-time EXIT approval. It never exits on its own.
 */
export class OcoManager {
  constructor(
    private readonly ops: TradeOps,
    private readonly broker: BrokerPort,
    private readonly policy: OcoPolicy,
  ) {}

  request(t: TradeRecord, quantity: number, netPosition: number, clientRef: string): OcoRequest {
    const p = t.proposal;
    return {
      clientRef,
      instrument: p.instrument,
      product: p.product,
      quantity,
      netPositionQuantity: netPosition,
      exitSide: p.direction === "LONG" ? "SELL" : "BUY",
      targetPrice: p.target,
      stopTriggerPrice: p.stopLoss,
    };
  }

  private elapsedSec(since: string | undefined): number {
    return since ? (this.ops.clock.now().getTime() - Date.parse(since)) / 1000 : Infinity;
  }

  /** `position` is the broker-confirmed signed net quantity; the caller has checked its sign. */
  async step(t: TradeRecord, position: number): Promise<TradeRecord> {
    const qty = Math.abs(position);
    if (qty === 0 || t.state === "EXIT_PENDING" || t.state === "PROTECTION_FAILED") return t;
    const seg = t.proposal.instrument.segment;

    // Submitted but no id yet (response lost): resolve by reference before anything else.
    if (!t.ocoId && t.ocoClientRef && t.state === "PROTECTION_PENDING") {
      const found = await this.broker.findOcoByClientRef(t.ocoClientRef, seg).catch(() => null);
      if (found) {
        t = await this.ops.patch(t, { ocoId: found.brokerOcoId }, "OCO_FOUND_BY_REF", { ocoId: found.brokerOcoId, ref: t.ocoClientRef });
      } else if (this.elapsedSec(t.ocoSubmittedAt) > this.policy.confirmTimeoutSec) {
        return this.fail(t, "OCO not found by reference after timeout", position);
      } else return t;
    }

    if (!t.ocoId) return this.submit(t, qty, position);
    const ocoId = t.ocoId;

    let snap: OcoSnapshot;
    try {
      snap = await this.broker.getOco(ocoId, seg);
    } catch (e) {
      await this.ops.audit(t.tradeId, "OCO_STATUS_ERROR", { error: (e as Error).message });
      if (this.elapsedSec(t.ocoSubmittedAt) > this.policy.confirmTimeoutSec && t.state !== "PROTECTED") return this.fail(t, "OCO status unavailable", position);
      return t;
    }

    switch (snap.status) {
      case "ACTIVE": {
        if (snap.quantity === qty) {
          if (t.state === "PROTECTED" && t.protectedQuantity === qty) return t;
          t = await this.ops.transition(t, "PROTECTED", { protectedQuantity: qty });
          await this.ops.audit(t.tradeId, "PROTECTION_CONFIRMED", { ocoId: t.ocoId, quantity: qty, stop: t.proposal.stopLoss, target: t.proposal.target });
          await this.ops.safeAlert(`🛡️ ${t.proposal.instrument.tradingSymbol}: protected ${qty} (stop ${t.proposal.stopLoss}, target ${t.proposal.target}). Broker confirmed the OCO is active.`);
          return t;
        }
        // Quantity differs (more entry fills, or position reduced elsewhere): resize, then re-confirm.
        if (t.state === "PROTECTED") t = await this.ops.transition(t, "POSITION_UNPROTECTED", { protectedQuantity: snap.quantity }, { reason: "position changed", position, ocoQuantity: snap.quantity });
        try {
          await this.broker.modifyOco(ocoId, seg, { quantity: qty });
          t = await this.ops.transition(t, "PROTECTION_PENDING", { ocoSubmittedAt: this.ops.now() }, { action: "OCO_RESIZE", from: snap.quantity, to: qty });
        } catch (e) {
          await this.ops.audit(t.tradeId, "OCO_RESIZE_FAILED", { error: (e as Error).message, from: snap.quantity, to: qty });
          return this.fail(t, `OCO resize failed: ${(e as Error).message}`, position, false);
        }
        return t;
      }
      case "PENDING":
      case "UNKNOWN":
        if (this.elapsedSec(t.ocoSubmittedAt) > this.policy.confirmTimeoutSec) {
          await this.broker.cancelOco(ocoId, seg).catch(() => undefined);
          return this.fail(t, `OCO not confirmed within ${this.policy.confirmTimeoutSec}s (status ${snap.rawStatus})`, position);
        }
        return t;
      case "TRIGGERED":
        return t; // an exit is in progress; the reconciler closes the trade when the position is flat
      case "COMPLETED":
        // The OCO finished but a position remains (it covered less than the position): protect the rest.
        await this.ops.audit(t.tradeId, "OCO_COMPLETED_POSITION_REMAINS", { position, ocoQuantity: snap.quantity });
        t = await this.toUnprotected(t, { ocoId: undefined, ocoClientRef: undefined, protectedQuantity: 0 });
        return this.submit(t, qty, position);
      case "FAILED":
      case "CANCELLED":
      case "EXPIRED":
        return this.fail(t, `OCO ${snap.status}${snap.remark ? `: ${snap.remark}` : ""}`, position);
    }
  }

  private async toUnprotected(t: TradeRecord, changes: Partial<TradeRecord>): Promise<TradeRecord> {
    return t.state === "POSITION_UNPROTECTED" ? this.ops.patch(t, changes) : this.ops.transition(t, "POSITION_UNPROTECTED", changes);
  }

  private async submit(t: TradeRecord, qty: number, position: number): Promise<TradeRecord> {
    if (t.ocoAttempts >= this.policy.maxAttempts) return this.fail(t, "OCO attempts exhausted", position, false);
    const ref = newRef("O");
    // Persist the reference first: if we crash after sending, the next cycle finds it by reference.
    t = await this.ops.transition(t, "PROTECTION_PENDING", { ocoClientRef: ref, ocoId: undefined, ocoSubmittedAt: this.ops.now(), ocoAttempts: t.ocoAttempts + 1 }, { action: "OCO_SUBMIT", ref, quantity: qty, attempt: t.ocoAttempts + 1 });
    try {
      const r = await this.broker.submitOco(this.request(t, qty, position, ref));
      return await this.ops.patch(t, { ocoId: r.brokerOcoId }, "OCO_ACCEPTED", { ocoId: r.brokerOcoId, rawStatus: r.rawStatus, note: "accepted is not active; confirming" });
    } catch (e) {
      if (e instanceof BrokerRejectedError) {
        await this.ops.audit(t.tradeId, "OCO_REJECTED", { error: e.message, code: e.code, attempt: t.ocoAttempts });
        t = await this.toUnprotected(t, { ocoClientRef: undefined, lastError: e.message });
        if (t.ocoAttempts >= this.policy.maxAttempts) return this.fail(t, `OCO rejected: ${e.message}`, position, false);
        return t; // retried next cycle
      }
      // Uncertain / network / auth: keep the reference and look it up next cycle.
      await this.ops.audit(t.tradeId, "OCO_SUBMIT_UNCERTAIN", { error: (e as Error).message, ref });
      return this.ops.patch(t, { lastError: (e as Error).message });
    }
  }

  /** One failed attempt. Retries while attempts remain, otherwise PROTECTION_FAILED. */
  private async fail(t: TradeRecord, reason: string, position: number, mayRetry = true): Promise<TradeRecord> {
    await this.ops.audit(t.tradeId, "OCO_ATTEMPT_FAILED", { reason, attempts: t.ocoAttempts });
    if (mayRetry && t.ocoAttempts < this.policy.maxAttempts) {
      t = await this.toUnprotected(t, { ocoId: undefined, ocoClientRef: undefined, lastError: reason });
      return this.submit(t, Math.abs(position), position);
    }
    t = await this.ops.transition(t, "PROTECTION_FAILED", { lastError: reason }, { reason });
    if (!t.flags.protectionFailedAlerted) {
      await this.ops.incident(t.tradeId, `${t.proposal.instrument.tradingSymbol}: position of ${Math.abs(position)} is NOT protected (${reason}). Place a stop in the Groww app or approve the exit request.`);
      t = await this.ops.patch(t, { flags: { ...t.flags, protectionFailedAlerted: true } });
    }
    return t;
  }
}

import { randomBytes, timingSafeEqual } from "node:crypto";
import { canonicalJson, sha256 } from "../audit/hash.js";
import type { TradeRecord } from "../domain/types.js";
import type { ApprovalKind, ApprovalRecord, Store } from "../store/Store.js";
import type { Clock } from "../util/clock.js";
import type { ApprovalCallback, Notifier } from "./ports.js";

/**
 * One-time approvals. Each approval:
 *  - is bound to an intent hash of the exact order (symbol, side, qty, prices, mode); any change voids it,
 *  - carries a random nonce in the Telegram button; only its sha256 is stored,
 *  - expires after APPROVAL_TTL_SEC,
 *  - is accepted only from an allow-listed user in the allow-listed chat,
 *  - is consumed atomically (PENDING -> APPROVED once), so a replayed or double-tapped button does nothing.
 */
export interface ApprovalPolicy {
  ttlSec: number;
  allowedChatId?: number;
  allowedUserIds: readonly number[];
}

export type CallbackOutcome =
  | { outcome: "APPROVED"; approval: ApprovalRecord }
  | { outcome: "DENIED"; approval: ApprovalRecord }
  | { outcome: "EXPIRED"; approval: ApprovalRecord; reason: string }
  | { outcome: "IGNORED"; reason: string };

export function orderIntent(t: TradeRecord): Record<string, unknown> {
  const p = t.proposal;
  return {
    tradeId: t.tradeId,
    mode: t.mode,
    tradingDay: t.tradingDay,
    symbol: p.instrument.tradingSymbol,
    exchange: p.instrument.exchange,
    segment: p.instrument.segment,
    direction: p.direction,
    product: p.product,
    entryType: p.entry.orderType,
    entryPrice: p.entry.price,
    entryTrigger: p.entry.triggerPrice ?? null,
    stopLoss: p.stopLoss,
    target: p.target,
    quantity: p.quantity,
    strategyId: p.strategyId,
  };
}

/** Exit intent: flatten exactly this quantity of this symbol for this trade. */
export function exitIntent(t: TradeRecord): Record<string, unknown> {
  return {
    tradeId: t.tradeId,
    mode: t.mode,
    action: "EXIT",
    symbol: t.proposal.instrument.tradingSymbol,
    segment: t.proposal.instrument.segment,
    exitSide: t.proposal.direction === "LONG" ? "SELL" : "BUY",
    quantity: Math.abs(t.confirmedPositionQuantity),
  };
}

export function intentHashFor(kind: ApprovalKind, t: TradeRecord): string {
  return sha256(canonicalJson(kind === "ENTRY" ? orderIntent(t) : exitIntent(t)));
}

export function intentHash(t: TradeRecord): string {
  return intentHashFor("ENTRY", t);
}

const b64url = (n: number) => randomBytes(n).toString("base64url");

function hashEq(a: string, b: string): boolean {
  const x = Buffer.from(a, "hex");
  const y = Buffer.from(b, "hex");
  return x.length === y.length && timingSafeEqual(x, y);
}

export class ApprovalService {
  constructor(
    private readonly store: Store,
    private readonly notifier: Notifier,
    private readonly clock: Clock,
    private readonly policy: ApprovalPolicy,
  ) {
    if (policy.allowedChatId === undefined || policy.allowedUserIds.length === 0) {
      throw new Error("Approvals need TELEGRAM_ALLOWED_CHAT_ID and TELEGRAM_ALLOWED_USER_IDS");
    }
  }

  async request(trade: TradeRecord, text: string, kind: ApprovalKind = "ENTRY"): Promise<ApprovalRecord> {
    const now = this.clock.now();
    const approvalId = b64url(12);
    const nonce = b64url(16);
    const rec: ApprovalRecord = {
      approvalId,
      tradeId: trade.tradeId,
      kind,
      intentHash: intentHashFor(kind, trade),
      nonceHash: sha256(nonce),
      status: "PENDING",
      createdAt: now.toISOString(),
      expiresAt: new Date(now.getTime() + this.policy.ttlSec * 1000).toISOString(),
    };
    await this.store.insertApproval(rec);
    await this.store.appendAudit({ at: now.toISOString(), tradeId: trade.tradeId, type: "APPROVAL_REQUESTED", payload: { approvalId, kind, intentHash: rec.intentHash, expiresAt: rec.expiresAt } });
    const msgId = await this.notifier.requestApproval(text, { approveData: `a|${approvalId}|${nonce}`, rejectData: `r|${approvalId}|${nonce}` });
    await this.store.setApprovalMessageId(approvalId, msgId);
    return { ...rec, telegramMessageId: msgId };
  }

  /**
   * Validates a button press. `currentTrade` must load the trade as it is NOW, so an intent that changed after
   * the request (re-sized, re-priced) cannot be approved with the old button.
   */
  async handleCallback(cb: ApprovalCallback, currentTrade: (tradeId: string) => Promise<TradeRecord | null>): Promise<CallbackOutcome> {
    const now = this.clock.now();
    const at = now.toISOString();
    const m = /^([ar])\|([A-Za-z0-9_-]{16})\|([A-Za-z0-9_-]{22})$/.exec(cb.data);
    if (!m) return { outcome: "IGNORED", reason: "unrecognised callback" };
    const [, action, approvalId, nonce] = m as unknown as [string, "a" | "r", string, string];

    if (cb.chatId !== this.policy.allowedChatId || !this.policy.allowedUserIds.includes(cb.fromUserId)) {
      await this.store.appendAudit({ at, tradeId: null, type: "APPROVAL_UNAUTHORIZED", payload: { approvalId, fromUserId: cb.fromUserId, chatId: cb.chatId } });
      return { outcome: "IGNORED", reason: "user or chat not allowed" };
    }
    const ap = await this.store.getApproval(approvalId);
    if (!ap || !hashEq(sha256(nonce), ap.nonceHash)) {
      await this.store.appendAudit({ at, tradeId: ap?.tradeId ?? null, type: "APPROVAL_BAD_NONCE", payload: { approvalId, fromUserId: cb.fromUserId } });
      return { outcome: "IGNORED", reason: "unknown approval or bad nonce" };
    }
    if (ap.status !== "PENDING") return { outcome: "IGNORED", reason: `approval already ${ap.status}` };

    const by = String(cb.fromUserId);
    if (now.getTime() > Date.parse(ap.expiresAt)) {
      const d = await this.store.decideApproval(approvalId, "EXPIRED", by, at);
      if (!d) return { outcome: "IGNORED", reason: "approval already decided" };
      await this.store.appendAudit({ at, tradeId: ap.tradeId, type: "APPROVAL_EXPIRED", payload: { approvalId, pressedAfterExpiry: true } });
      return { outcome: "EXPIRED", approval: d, reason: "approval expired" };
    }

    if (action === "r") {
      const d = await this.store.decideApproval(approvalId, "DENIED", by, at);
      if (!d) return { outcome: "IGNORED", reason: "approval already decided" };
      await this.store.appendAudit({ at, tradeId: ap.tradeId, type: "APPROVAL_DENIED", payload: { approvalId, by } });
      return { outcome: "DENIED", approval: d };
    }

    const trade = await currentTrade(ap.tradeId);
    if (!trade || intentHashFor(ap.kind, trade) !== ap.intentHash) {
      const d = await this.store.decideApproval(approvalId, "EXPIRED", by, at);
      await this.store.appendAudit({ at, tradeId: ap.tradeId, type: "APPROVAL_VOID_INTENT_CHANGED", payload: { approvalId } });
      return d ? { outcome: "EXPIRED", approval: d, reason: "order changed after the request" } : { outcome: "IGNORED", reason: "approval already decided" };
    }
    const d = await this.store.decideApproval(approvalId, "APPROVED", by, at);
    if (!d) return { outcome: "IGNORED", reason: "approval already decided" };
    await this.store.appendAudit({ at, tradeId: ap.tradeId, type: "APPROVAL_GRANTED", payload: { approvalId, kind: ap.kind, by, intentHash: ap.intentHash } });
    return { outcome: "APPROVED", approval: d };
  }

  /** Expires a pending approval whose time is up. Returns the record if this call expired it. */
  async expireIfDue(approvalId: string): Promise<ApprovalRecord | null> {
    const ap = await this.store.getApproval(approvalId);
    const now = this.clock.now();
    if (!ap || ap.status !== "PENDING" || now.getTime() <= Date.parse(ap.expiresAt)) return null;
    const d = await this.store.decideApproval(approvalId, "EXPIRED", undefined, now.toISOString());
    if (d) await this.store.appendAudit({ at: now.toISOString(), tradeId: ap.tradeId, type: "APPROVAL_EXPIRED", payload: { approvalId } });
    return d;
  }
}

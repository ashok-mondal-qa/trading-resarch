import { randomUUID } from "node:crypto";
import type { AppConfig } from "../config/config.js";
import type { OrderRequest, TradeProposal, TradeRecord } from "../domain/types.js";
import { BrokerRejectedError, type BrokerPort, type QuoteSource } from "../broker/BrokerPort.js";
import type { ApprovalService } from "../approval/ApprovalService.js";
import { approvalText, decisionLine } from "../approval/messages.js";
import type { ApprovalCallback, Notifier } from "../approval/ports.js";
import type { TelegramCommand } from "../approval/TelegramGateway.js";
import { validate } from "../risk/riskEngine.js";
import type { Store } from "../store/Store.js";
import { hhmm, istMinutes, type Clock } from "../util/clock.js";
import { OcoManager, newRef } from "./OcoManager.js";
import { Reconciler } from "./Reconciler.js";
import { HALT_KEY, TradeOps } from "./TradeOps.js";

export interface EngineDeps {
  cfg: AppConfig;
  store: Store;
  broker: BrokerPort;
  quotes: QuoteSource;
  approvals: ApprovalService;
  notifier: Notifier;
  clock: Clock;
  /** LIVE_APPROVAL: the strategy ids the live gate verified as ACCEPTED. PAPER: undefined. */
  allowedStrategyIds?: ReadonlySet<string>;
}

/**
 * Orchestrates one trade at a time:
 *   propose -> risk -> daily slot -> Telegram approval -> risk re-check with a fresh quote -> entry
 *   -> reconcile fills/position -> OCO protection -> close.
 * Entries happen ONLY inside handleCallback() after ApprovalService consumed a valid one-time approval.
 */
export class ExecutionService {
  readonly ops: TradeOps;
  readonly oco: OcoManager;
  readonly reconciler: Reconciler;

  constructor(private readonly d: EngineDeps) {
    if (d.cfg.mode === "LIVE_APPROVAL" && d.broker.kind !== "GROWW") throw new Error("LIVE_APPROVAL needs the Groww broker");
    if (d.cfg.mode === "PAPER" && d.broker.kind !== "PAPER") throw new Error("PAPER mode must use the paper broker");
    if (d.cfg.mode === "LIVE_APPROVAL" && !d.allowedStrategyIds?.size) throw new Error("LIVE_APPROVAL needs gate-verified strategy ids");
    this.ops = new TradeOps(d.store, d.clock, d.notifier);
    this.oco = new OcoManager(this.ops, d.broker, d.cfg.oco);
    this.reconciler = new Reconciler(this.ops, d.broker, this.oco, d.cfg.risk);
  }

  private async halted(): Promise<boolean> {
    return !!(await this.d.store.getKv(HALT_KEY)); // null or "" = not halted
  }

  private async riskCheck(t: TradeRecord, p: TradeProposal) {
    let existing = 0;
    let positionError: string | undefined;
    try {
      existing = (await this.d.broker.getPosition(p.instrument.tradingSymbol, p.instrument.segment)).netQuantity;
    } catch (e) {
      positionError = (e as Error).message;
    }
    const decision = validate(
      p,
      {
        now: this.d.clock.now(),
        mode: this.d.cfg.mode,
        killSwitch: this.d.cfg.killSwitch,
        halted: await this.halted(),
        existingPositionQty: existing,
        dailySlotHolder: await this.d.store.dailySlotHolder(this.d.cfg.mode, p.tradingDay),
        tradeId: t.tradeId,
        allowedStrategyIds: this.d.allowedStrategyIds,
      },
      this.d.cfg.risk,
    );
    if (positionError) {
      decision.approved = false;
      decision.reasons.push(`cannot confirm current positions (${positionError}): DATA INSUFFICIENT`);
    }
    return decision;
  }

  /** Entry point for the research side. Returns the stored trade (possibly RISK_REJECTED). */
  async propose(p: TradeProposal): Promise<TradeRecord> {
    const now = this.ops.now();
    let t: TradeRecord = {
      tradeId: randomUUID(),
      mode: this.d.cfg.mode,
      tradingDay: p.tradingDay,
      proposal: p,
      state: "PROPOSED",
      risk: null,
      entryClientRef: newRef("E"),
      filledQuantity: 0,
      confirmedPositionQuantity: 0,
      protectedQuantity: 0,
      ocoAttempts: 0,
      flags: {},
      version: 1,
      createdAt: now,
      updatedAt: now,
    };
    await this.d.store.insertTrade(t);
    await this.ops.audit(t.tradeId, "PROPOSAL_RECEIVED", { proposal: p });

    const decision = await this.riskCheck(t, p);
    if (!decision.approved) {
      t = await this.ops.transition(t, "RISK_REJECTED", { risk: decision }, { reasons: decision.reasons });
      await this.ops.safeAlert(`NO TRADE: ${p.instrument.tradingSymbol} (${p.strategyId}) rejected by the risk engine:\n- ${decision.reasons.join("\n- ")}`);
      return t;
    }
    if (!(await this.d.store.claimDailySlot(this.d.cfg.mode, p.tradingDay, t.tradeId))) {
      const reasons = ["today's one trade is already used"];
      t = await this.ops.transition(t, "RISK_REJECTED", { risk: { ...decision, approved: false, reasons } }, { reasons });
      return t;
    }
    t = await this.ops.transition(t, "AWAITING_APPROVAL", { risk: decision }, { metrics: decision.metrics as unknown as Record<string, unknown> });
    const ap = await this.d.approvals.request(t, approvalText(t, this.d.cfg.approvalTtlSec), "ENTRY");
    return this.ops.patch(t, { approvalId: ap.approvalId });
  }

  /** A Telegram button press. The only path that can send an entry or a manual exit. */
  async handleCallback(cb: ApprovalCallback): Promise<void> {
    const res = await this.d.approvals.handleCallback(cb, (id) => this.d.store.getTrade(id));
    const reply = res.outcome === "IGNORED" ? `Ignored: ${res.reason}` : res.outcome;
    await this.d.notifier.answerCallback?.(cb.callbackQueryId, reply).catch(() => undefined);
    if (res.outcome === "IGNORED") return;

    const ap = res.approval;
    let t = await this.d.store.getTrade(ap.tradeId);
    if (!t) return;
    if (ap.telegramMessageId !== undefined || cb.messageId !== undefined) {
      const detail = res.outcome === "EXPIRED" ? res.reason : "";
      await this.d.notifier.closeApproval((ap.telegramMessageId ?? cb.messageId)!, `${decisionLine(res.outcome, detail)}\n${t.proposal.instrument.tradingSymbol} ${ap.kind}`).catch(() => undefined);
    }

    if (ap.kind === "EXIT") {
      if (res.outcome === "APPROVED") await this.executeExit(t);
      else t = await this.ops.patch(t, { exitApprovalId: undefined });
      return;
    }

    if (t.state !== "AWAITING_APPROVAL" || t.approvalId !== ap.approvalId) return;
    if (res.outcome === "DENIED") {
      await this.ops.transition(t, "APPROVAL_DENIED");
      return;
    }
    if (res.outcome === "EXPIRED") {
      await this.ops.transition(t, "APPROVAL_EXPIRED", {}, { reason: res.reason });
      return;
    }
    t = await this.ops.transition(t, "APPROVED");
    await this.enterApproved(t);
  }

  private async enterApproved(t: TradeRecord): Promise<TradeRecord> {
    const p = t.proposal;
    // Re-check everything with a fresh quote: prices move while the owner reads the message.
    let fresh: TradeProposal;
    try {
      const q = await this.d.quotes.getLtp(p.instrument);
      fresh = { ...p, referencePrice: q.price, dataTimestamp: q.at };
    } catch (e) {
      const reasons = [`no fresh quote at approval time (${(e as Error).message}): DATA INSUFFICIENT`];
      await this.ops.safeAlert(`Not sent: ${p.instrument.tradingSymbol}. ${reasons[0]}`);
      return this.ops.transition(t, "RISK_REJECTED", { risk: { approved: false, reasons, metrics: null, checkedAt: this.ops.now() } }, { reasons, stage: "post-approval" });
    }
    const decision = await this.riskCheck(t, fresh);
    if (!decision.approved) {
      await this.ops.safeAlert(`Not sent: ${p.instrument.tradingSymbol} failed the re-check after approval:\n- ${decision.reasons.join("\n- ")}`);
      return this.ops.transition(t, "RISK_REJECTED", { risk: decision }, { reasons: decision.reasons, stage: "post-approval" });
    }

    const long = p.direction === "LONG";
    const req: OrderRequest = {
      clientRef: t.entryClientRef,
      instrument: p.instrument,
      side: long ? "BUY" : "SELL",
      product: p.product,
      orderType: p.entry.orderType,
      quantity: p.quantity,
      price: p.entry.price,
      triggerPrice: p.entry.triggerPrice,
      validity: "DAY",
    };
    // Persist intent before sending, so a crash leaves ENTRY_SUBMITTING (resolved by reference lookup).
    t = await this.ops.transition(t, "ENTRY_SUBMITTING", { risk: decision }, { request: req as unknown as Record<string, unknown> });
    try {
      const ack = await this.d.broker.submitOrder(req);
      t = await this.ops.transition(t, "ENTRY_PENDING", { entryOrderId: ack.brokerOrderId }, { brokerOrderId: ack.brokerOrderId, rawStatus: ack.rawStatus, note: "accepted, not filled" });
      await this.ops.safeAlert(`📨 ${p.instrument.tradingSymbol}: entry order accepted by the broker (${t.mode}). Not filled yet; you will get a message on each confirmed fill.`);
    } catch (e) {
      if (e instanceof BrokerRejectedError) {
        t = await this.ops.transition(t, "ENTRY_REJECTED", { lastError: e.message }, { error: e.message, code: e.code });
        await this.ops.safeAlert(`❌ ${p.instrument.tradingSymbol}: entry rejected by the broker: ${e.message}`);
      } else {
        t = await this.ops.transition(t, "ENTRY_UNCERTAIN", { lastError: (e as Error).message }, { error: (e as Error).message });
      }
    }
    return t;
  }

  /** Owner-approved flatten: cancel the OCO, confirm it did not fire, then exit the broker-confirmed quantity. */
  private async executeExit(t: TradeRecord): Promise<void> {
    const p = t.proposal;
    const seg = p.instrument.segment;
    if (t.ocoId) {
      await this.d.broker.cancelOco(t.ocoId, seg).catch(() => undefined);
      const snap = await this.d.broker.getOco(t.ocoId, seg).catch(() => null);
      if (snap && (snap.status === "TRIGGERED" || snap.status === "COMPLETED" || snap.status === "ACTIVE" || snap.status === "PENDING")) {
        await this.ops.safeAlert(`Exit not sent: the OCO is ${snap.status} and may already be exiting. Check the Groww app.`);
        await this.ops.patch(t, { exitApprovalId: undefined }, "EXIT_ABORTED", { ocoStatus: snap.status });
        return;
      }
    }
    const pos = (await this.d.broker.getPosition(p.instrument.tradingSymbol, seg)).netQuantity;
    if (pos === 0) {
      await this.ops.audit(t.tradeId, "EXIT_NOT_NEEDED", { position: 0 });
      return;
    }
    const ref = newRef("X");
    t = await this.ops.transition(t, "EXIT_PENDING", { exitClientRef: ref }, { position: pos });
    try {
      const ack = await this.d.broker.submitOrder({
        clientRef: ref,
        instrument: p.instrument,
        side: pos > 0 ? "SELL" : "BUY",
        product: p.product,
        orderType: "MARKET",
        quantity: Math.abs(pos),
        validity: "DAY",
      });
      await this.ops.patch(t, { exitOrderId: ack.brokerOrderId }, "EXIT_ACCEPTED", { brokerOrderId: ack.brokerOrderId });
    } catch (e) {
      await this.ops.safeAlert(`⚠️ Exit order for ${p.instrument.tradingSymbol} failed: ${(e as Error).message}. Exit in the Groww app.`);
      await this.ops.transition(t, "POSITION_UNPROTECTED", { exitClientRef: undefined, exitApprovalId: undefined, ocoId: undefined, ocoClientRef: undefined, protectedQuantity: 0 }, { error: (e as Error).message });
    }
  }

  private async requestExit(t: TradeRecord, why: string): Promise<TradeRecord> {
    if (t.exitApprovalId) return t;
    const qty = Math.abs(t.confirmedPositionQuantity);
    const text = [
      t.mode === "LIVE_APPROVAL" ? "🔴 LIVE EXIT approval (real money)" : "🧪 PAPER exit approval",
      `${t.proposal.instrument.tradingSymbol}: ${why}`,
      `Exit ${qty} at MARKET now (${t.proposal.direction === "LONG" ? "SELL" : "BUY"}).`,
      `This button works once and expires in ${this.d.cfg.approvalTtlSec}s.`,
    ].join("\n");
    const ap = await this.d.approvals.request(t, text, "EXIT");
    return this.ops.patch(t, { exitApprovalId: ap.approvalId }, "EXIT_APPROVAL_REQUESTED", { why });
  }

  /** Telegram text commands from the allow-listed user. Only risk-reducing actions are available here. */
  async handleCommand(cmd: TelegramCommand): Promise<void> {
    const tg = this.d.cfg.telegram;
    if (cmd.chatId !== tg.allowedChatId || !tg.allowedUserIds.includes(cmd.fromUserId)) {
      await this.ops.audit(null, "COMMAND_UNAUTHORIZED", { fromUserId: cmd.fromUserId, chatId: cmd.chatId });
      return;
    }
    if (cmd.text === "/halt") {
      await this.d.store.setKv(HALT_KEY, `telegram:${cmd.fromUserId}:${this.ops.now()}`);
      await this.ops.audit(null, "HALTED_BY_OWNER", { by: cmd.fromUserId });
      await this.ops.safeAlert("⏸️ Halted: no new entries. Open positions stay protected by their OCOs. Clear the halt on the server (npm run cli -- clear-halt).");
    } else if (cmd.text === "/status") {
      const open = await this.d.store.listOpenTrades(this.d.cfg.mode);
      const lines = open.map((t) => `${t.proposal.instrument.tradingSymbol} ${t.state} filled ${t.filledQuantity} position ${t.confirmedPositionQuantity} protected ${t.protectedQuantity}`);
      await this.ops.safeAlert(`Mode ${this.d.cfg.mode}. Halted: ${(await this.halted()) ? "yes" : "no"}.\n${lines.join("\n") || "No open trades."}`);
    }
  }

  /** One engine cycle: expire approvals, reconcile every open trade, ask for exits where needed. */
  async tick(): Promise<void> {
    const nowMin = istMinutes(this.d.clock.now());
    for (let t of await this.d.store.listOpenTrades(this.d.cfg.mode)) {
      try {
        if (t.state === "AWAITING_APPROVAL" && t.approvalId) {
          const exp = await this.d.approvals.expireIfDue(t.approvalId);
          if (exp) {
            await this.ops.transition(t, "APPROVAL_EXPIRED");
            if (exp.telegramMessageId !== undefined) await this.d.notifier.closeApproval(exp.telegramMessageId, decisionLine("EXPIRED", "no answer in time")).catch(() => undefined);
          }
          continue;
        }
        if (t.exitApprovalId) {
          const exp = await this.d.approvals.expireIfDue(t.exitApprovalId);
          if (exp) t = await this.ops.patch(t, { exitApprovalId: undefined });
        }
        t = await this.reconciler.reconcile(t);
        const holding = t.confirmedPositionQuantity !== 0;
        if (holding && t.state === "PROTECTION_FAILED") {
          t = await this.requestExit(t, "the position is NOT protected (OCO failed).");
        } else if (holding && t.proposal.product === "MIS" && nowMin >= hhmm(this.d.cfg.risk.squareOffTime) && !t.flags.squareOffAsked && t.state !== "EXIT_PENDING") {
          t = await this.ops.patch(t, { flags: { ...t.flags, squareOffAsked: true } });
          t = await this.requestExit(t, `square-off time ${this.d.cfg.risk.squareOffTime} reached for an intraday position.`);
        }
      } catch (e) {
        await this.ops.audit(t.tradeId, "RECONCILE_ERROR", { error: (e as Error).message, state: t.state });
      }
    }
  }
}

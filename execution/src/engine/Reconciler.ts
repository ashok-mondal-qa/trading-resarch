import type { RiskConfig } from "../config/config.js";
import type { Fill, TradeRecord } from "../domain/types.js";
import type { BrokerPort } from "../broker/BrokerPort.js";
import { roundTripCharges } from "../risk/charges.js";
import { hhmm, istMinutes } from "../util/clock.js";
import type { OcoManager } from "./OcoManager.js";
import type { TradeOps } from "./TradeOps.js";

/** After this IST time an order that still cannot be found is treated as never placed (position must be 0). */
const UNCERTAIN_GIVE_UP = "15:35";

/**
 * Brings each open trade in line with what the broker reports. Broker truth wins:
 *  - filled quantity = sum of the broker's trade list for the entry order (never the status alone),
 *  - position = the broker's net quantity for the symbol,
 *  - any disagreement is a safety incident (new entries blocked), and the ACTUAL position is protected.
 */
export class Reconciler {
  constructor(
    private readonly ops: TradeOps,
    private readonly broker: BrokerPort,
    private readonly oco: OcoManager,
    private readonly risk: RiskConfig,
  ) {}

  async reconcile(t: TradeRecord): Promise<TradeRecord> {
    const seg = t.proposal.instrument.segment;
    const sym = t.proposal.instrument.tradingSymbol;
    const sign = t.proposal.direction === "LONG" ? 1 : -1;
    const nowMin = istMinutes(this.ops.clock.now());

    if (t.state === "ENTRY_SUBMITTING") {
      // Crashed between persisting ENTRY_SUBMITTING and recording the broker's answer.
      t = await this.ops.transition(t, "ENTRY_UNCERTAIN", {}, { reason: "recovered from ENTRY_SUBMITTING" });
    }

    if (t.state === "ENTRY_UNCERTAIN") {
      const found = await this.broker.findOrderByClientRef(t.entryClientRef, seg).catch(() => null);
      if (found) {
        t = await this.ops.transition(t, "ENTRY_PENDING", { entryOrderId: found.brokerOrderId }, { foundByRef: t.entryClientRef });
      } else {
        const pos = (await this.broker.getPosition(sym, seg)).netQuantity;
        if (pos !== 0) {
          await this.ops.incident(t.tradeId, `${sym}: entry order not found by reference but a position of ${pos} exists`, { position: pos });
          t = await this.ops.transition(t, "POSITION_UNPROTECTED", { confirmedPositionQuantity: pos });
          return pos * sign > 0 ? this.oco.step(t, pos) : this.halt(t, "position opposite to the trade direction");
        }
        if (nowMin >= hhmm(UNCERTAIN_GIVE_UP)) {
          return this.ops.transition(t, "ENTRY_CANCELLED", { closeReason: "order never found by reference; no position at end of day" });
        }
        if (!t.flags.uncertainAlerted) {
          await this.ops.safeAlert(`❓ ${sym}: the entry order's outcome is unknown (network). It will not be resent. Checking every few seconds; also check the Groww app.`);
          t = await this.ops.patch(t, { flags: { ...t.flags, uncertainAlerted: true } });
        }
        return t;
      }
    }

    if (!t.entryOrderId) return t;
    const entryOrderId = t.entryOrderId;
    if (!["ENTRY_PENDING", "POSITION_UNPROTECTED", "PROTECTION_PENDING", "PROTECTED", "PROTECTION_FAILED", "EXIT_PENDING"].includes(t.state)) return t;

    const order = await this.broker.getOrder(entryOrderId, seg);
    const fills = await this.broker.listFills(entryOrderId, seg);
    const filled = fills.reduce((s, f) => s + f.quantity, 0);
    const pos = (await this.broker.getPosition(sym, seg)).netQuantity;

    if (filled !== t.filledQuantity) {
      const avg = filled ? fills.reduce((s, f) => s + f.quantity * f.price, 0) / filled : undefined;
      t = await this.ops.patch(t, { filledQuantity: filled, averageEntryPrice: avg }, "ENTRY_FILLS", { filled, ordered: order.orderedQuantity, average: avg, fills: fills.map((f) => ({ id: f.brokerTradeId, q: f.quantity, p: f.price })) });
      await this.ops.safeAlert(`✅ ${sym}: entry filled ${filled}/${order.orderedQuantity} @ avg ${avg?.toFixed(2)} (from the broker's trade list).`);
    }
    if (order.reportedFilledQuantity > filled) {
      await this.ops.audit(t.tradeId, "FILL_LAG", { orderSays: order.reportedFilledQuantity, tradeList: filled });
    }

    // Unfilled remainder after the entry window (or once an exit has started) is cancelled. Cancelling only
    // reduces exposure, so it does not need a new approval.
    const entryOpen = order.status === "PENDING" || order.status === "PARTIALLY_FILLED";
    const exiting = t.state === "EXIT_PENDING" || (t.ocoId !== undefined && pos === 0 && filled > 0);
    if (entryOpen && (nowMin > hhmm(this.risk.entryWindowEnd) || exiting)) {
      await this.broker.cancelOrder(entryOrderId, seg).then(
        () => this.ops.audit(t.tradeId, "ENTRY_REMAINDER_CANCELLED", { filled, ordered: order.orderedQuantity }),
        (e) => this.ops.audit(t.tradeId, "ENTRY_CANCEL_FAILED", { error: (e as Error).message }),
      );
    }

    if (filled === 0 && pos === 0) {
      if (t.state !== "ENTRY_PENDING") return t;
      if (order.status === "REJECTED") return this.ops.transition(t, "ENTRY_REJECTED", { closeReason: order.remark ?? "rejected by broker" });
      if (order.status === "CANCELLED") return this.ops.transition(t, "ENTRY_CANCELLED", { closeReason: "cancelled with no fills" });
      return t;
    }

    if (pos * sign < 0) return this.halt(t, `broker position ${pos} is opposite to the trade direction`);

    if (t.state === "ENTRY_PENDING") t = await this.ops.transition(t, "POSITION_UNPROTECTED", { confirmedPositionQuantity: pos }, { filled, position: pos });

    if (pos === 0) return this.close(t, fills);

    // Before any exit, the position must equal the fills. Otherwise: incident, but protect what exists.
    const exitStarted = t.state === "EXIT_PENDING" || Math.abs(pos) < t.protectedQuantity;
    const lagOnly = Math.abs(pos) === order.reportedFilledQuantity; // trade list behind the order record
    if (!exitStarted && Math.abs(pos) !== filled && !lagOnly && !t.flags.mismatchReported) {
      await this.ops.incident(t.tradeId, `${sym}: broker position ${pos} does not match entry fills ${filled}. Protecting the actual position.`, { position: pos, filled });
      t = await this.ops.patch(t, { flags: { ...t.flags, mismatchReported: true } });
    }
    if (pos !== t.confirmedPositionQuantity) t = await this.ops.patch(t, { confirmedPositionQuantity: pos }, "POSITION", { position: pos });

    if (t.state === "EXIT_PENDING") return this.checkExitOrder(t);
    return this.oco.step(t, pos);
  }

  private async checkExitOrder(t: TradeRecord): Promise<TradeRecord> {
    if (!t.exitOrderId) return t;
    const o = await this.broker.getOrder(t.exitOrderId, t.proposal.instrument.segment);
    if (o.status === "REJECTED" || o.status === "CANCELLED") {
      await this.ops.safeAlert(`⚠️ ${t.proposal.instrument.tradingSymbol}: exit order ${o.status}${o.remark ? ` (${o.remark})` : ""}. Position still open; exit in the Groww app.`);
      return this.ops.transition(t, "POSITION_UNPROTECTED", { exitOrderId: undefined, exitApprovalId: undefined, ocoId: undefined, ocoClientRef: undefined, protectedQuantity: 0 }, { exitOrder: o.status });
    }
    return t;
  }

  /** Position is flat: make sure nothing is left working, then record the result. */
  private async close(t: TradeRecord, entryFills: Fill[]): Promise<TradeRecord> {
    const seg = t.proposal.instrument.segment;
    let exit: { price: number; quantity: number; leg?: string } | undefined;
    let reason = "position flat";
    if (t.ocoId) {
      const snap = await this.broker.getOco(t.ocoId, seg).catch(() => null);
      if (snap && (snap.status === "ACTIVE" || snap.status === "PENDING")) {
        // An OCO left working on a flat position could open a new one. Cancel it.
        await this.broker.cancelOco(t.ocoId, seg).catch(async (e) => {
          await this.ops.incident(t.tradeId, `${t.proposal.instrument.tradingSymbol}: position is flat but the OCO could not be cancelled (${(e as Error).message}). Cancel it in the Groww app.`);
        });
        reason = "closed outside the OCO (manual exit?)";
      } else if (snap?.status === "COMPLETED" || snap?.status === "TRIGGERED") {
        exit = (await this.broker.describeExit?.(t.ocoId, seg)) ?? undefined;
        reason = exit ? `OCO ${exit.leg} leg` : "OCO completed";
      }
    }
    if (!exit && t.exitOrderId) {
      const fills = await this.broker.listFills(t.exitOrderId, seg);
      const q = fills.reduce((s, f) => s + f.quantity, 0);
      if (q > 0) exit = { price: fills.reduce((s, f) => s + f.quantity * f.price, 0) / q, quantity: q, leg: "MANUAL_EXIT" };
      reason = "exit approved by owner";
    }
    let pnl: number | undefined;
    const filled = entryFills.reduce((s, f) => s + f.quantity, 0);
    if (exit && t.averageEntryPrice !== undefined && filled > 0) {
      const sign = t.proposal.direction === "LONG" ? 1 : -1;
      const gross = sign * (exit.price - t.averageEntryPrice) * exit.quantity;
      const charges = roundTripCharges(t.proposal.instrument, t.proposal.product, sign > 0 ? "BUY" : "SELL", t.averageEntryPrice, exit.price, exit.quantity, 0).total;
      pnl = gross - charges;
    }
    t = await this.ops.transition(t, "CLOSED", { confirmedPositionQuantity: 0, exitPrice: exit?.price, realisedPnlInr: pnl, closeReason: reason }, { exit, pnlAfterEstimatedCharges: pnl });
    await this.ops.safeAlert(
      `🏁 ${t.proposal.instrument.tradingSymbol} closed: ${reason}.` +
        (exit ? ` Exit ${exit.price.toFixed(2)}; P&L after estimated charges ₹${pnl?.toFixed(2)}.` : " Exit price unknown here; check the contract note.") +
        ` Mode ${t.mode}.`,
    );
    return t;
  }

  private async halt(t: TradeRecord, reason: string): Promise<TradeRecord> {
    await this.ops.incident(t.tradeId, `${t.proposal.instrument.tradingSymbol}: ${reason}. Automation stopped for this trade.`);
    return this.ops.transition(t, "HALTED", { lastError: reason });
  }
}

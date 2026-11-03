import type { TradeRecord } from "../domain/types.js";

const inr = (v: number | undefined) => (v === undefined ? "n/a" : `₹${v.toFixed(2)}`);

/**
 * Approval request text. Built only from trade fields: no account ids, tokens or keys.
 * Follows the brief's daily output fields that apply to a single proposal.
 */
export function approvalText(t: TradeRecord, ttlSec: number): string {
  const p = t.proposal;
  const m = t.risk?.metrics;
  const side = p.direction === "LONG" ? "BUY" : "SELL";
  const live = t.mode === "LIVE_APPROVAL";
  return [
    live ? "🔴 LIVE ORDER APPROVAL (real money)" : "🧪 PAPER order approval (simulated)",
    `Date: ${p.tradingDay}`,
    `Instrument: ${p.instrument.tradingSymbol} (${p.instrument.segment}, ${p.product})`,
    `Direction: ${p.direction} (${side} ${p.quantity})`,
    `Strategy: ${p.strategyId}`,
    `Entry: ${p.entry.orderType} ${p.entry.price}${p.entry.triggerPrice ? ` trigger ${p.entry.triggerPrice}` : ""}`,
    `Stop-loss: ${p.stopLoss}   Target: ${p.target}`,
    `Max planned risk (incl. slippage + charges): ${inr(m?.plannedRiskInr)}`,
    `Estimated charges at stop: ${inr(m?.chargesAtStopInr)} (rates unverified, buffered)`,
    `Net reward:risk: 1:${m ? m.rewardRiskNet.toFixed(2) : "n/a"}`,
    `Order value: ${inr(m?.notionalInr)}`,
    `Data timestamp: ${p.dataTimestamp}`,
    "",
    "A gap through the stop can lose more than planned.",
    `This button works once and expires in ${ttlSec}s. Protective OCO (stop + target) is placed automatically only after the broker confirms a fill.`,
  ].join("\n");
}

export function decisionLine(outcome: string, detail = ""): string {
  return `Decision: ${outcome}${detail ? ` (${detail})` : ""}`;
}

import type { ExecutionMode, RiskDecision, RiskMetrics, Side, TradeProposal } from "../domain/types.js";
import type { RiskConfig } from "../config/config.js";
import { HARD_LIMITS } from "../config/config.js";
import { hhmm, istDay, istMinutes, isIstWeekend } from "../util/clock.js";
import { DEFAULT_RATES, roundTripCharges, type ChargeRates } from "./charges.js";

export interface RiskContext {
  now: Date;
  mode: ExecutionMode;
  killSwitch: boolean;
  halted: boolean;
  /** Broker-reported signed net quantity already held in this symbol. */
  existingPositionQty: number;
  /** Trade id already holding today's slot (null = free). The trade being checked may hold it itself. */
  dailySlotHolder: string | null;
  tradeId?: string;
  /** In LIVE_APPROVAL: the ACCEPTED strategy ids from the gate. In PAPER: undefined (any id allowed). */
  allowedStrategyIds?: ReadonlySet<string>;
}

const EPS = 1e-6;

function onTick(price: number, tick: number): boolean {
  const n = price / tick;
  return Math.abs(n - Math.round(n)) < 1e-6;
}

function slip(price: number, bps: number, tick: number, minTicks: number): number {
  return Math.max((price * bps) / 10_000, tick * minTicks);
}

/** Planned-risk arithmetic for a given quantity. Pure; used by validate() and maxQuantity(). */
export function computeMetrics(p: TradeProposal, qty: number, cfg: RiskConfig, rates: ChargeRates = DEFAULT_RATES): RiskMetrics {
  const long = p.direction === "LONG";
  const entrySide: Side = long ? "BUY" : "SELL";
  const tick = p.instrument.tickSize;
  const entry = p.entry.price;
  const perUnitRisk = Math.abs(entry - p.stopLoss);
  const entrySlip = slip(entry, cfg.slippageBpsEntry, tick, cfg.slippageMinTicks);
  const stopSlip = slip(p.stopLoss, cfg.slippageBpsStop, tick, cfg.slippageMinTicks);
  const targetSlip = slip(p.target, cfg.slippageBpsEntry, tick, cfg.slippageMinTicks);

  // Worst-case fills: entry worse by entrySlip, stop exit worse by stopSlip.
  const worstEntry = long ? entry + entrySlip : entry - entrySlip;
  const worstStopExit = long ? p.stopLoss - stopSlip : p.stopLoss + stopSlip;
  const chargesAtStop = roundTripCharges(p.instrument, p.product, entrySide, worstEntry, worstStopExit, qty, cfg.chargesSafetyBufferPct, rates);
  const chargesAtTarget = roundTripCharges(p.instrument, p.product, entrySide, worstEntry, p.target, qty, cfg.chargesSafetyBufferPct, rates);

  const grossRiskInr = qty * perUnitRisk;
  const slippageInr = qty * (entrySlip + stopSlip);
  const plannedRiskInr = grossRiskInr + slippageInr + chargesAtStop.total;
  const netRewardInr = qty * (Math.abs(p.target - entry) - entrySlip - targetSlip) - chargesAtTarget.total;
  return {
    perUnitRisk,
    grossRiskInr,
    slippageInr,
    chargesAtStopInr: chargesAtStop.total,
    chargesAtTargetInr: chargesAtTarget.total,
    plannedRiskInr,
    netRewardInr,
    rewardRiskNet: plannedRiskInr > 0 ? netRewardInr / plannedRiskInr : 0,
    notionalInr: qty * worstEntry,
  };
}

/**
 * Largest quantity (a multiple of the lot size) whose planned risk fits the cap and whose notional fits the
 * cash cap. Returns 0 when even one lot does not fit. The proposal's own quantity is ignored.
 */
export function maxQuantity(p: TradeProposal, cfg: RiskConfig, rates: ChargeRates = DEFAULT_RATES): number {
  const lot = p.instrument.lotSize;
  let best = 0;
  // Charges are not linear (brokerage cap), so walk lots; quantities here are small (₹300 / risk per unit).
  for (let lots = 1; lots <= 100_000; lots++) {
    const q = lots * lot;
    const m = computeMetrics(p, q, cfg, rates);
    if (m.plannedRiskInr > cfg.maxPlannedRiskInr + EPS || m.notionalInr > cfg.maxNotionalInr + EPS) break;
    best = q;
  }
  return best;
}

/**
 * Deterministic risk validation. Final authority on eligibility: if this says no, nothing is sent.
 * Every reason is collected (not just the first) so the owner sees the full picture in Telegram.
 */
export function validate(p: TradeProposal, ctx: RiskContext, cfg: RiskConfig, rates: ChargeRates = DEFAULT_RATES): RiskDecision {
  const reasons: string[] = [];
  const now = ctx.now;
  const inst = p.instrument;
  const long = p.direction === "LONG";

  if (cfg.maxPlannedRiskInr > HARD_LIMITS.maxPlannedRiskInr) reasons.push("config risk cap above the ₹300 hard limit");
  if (cfg.minRewardRisk < HARD_LIMITS.minRewardRisk) reasons.push("config R:R below the 1:2 hard limit");
  if (ctx.killSwitch) reasons.push("kill switch is on");
  if (ctx.halted) reasons.push("engine is halted after an earlier incident; owner must clear it");

  // Calendar and time.
  const today = istDay(now);
  if (p.tradingDay !== today) reasons.push(`proposal is for ${p.tradingDay}, today (IST) is ${today}`);
  if (isIstWeekend(now) || cfg.holidays.includes(today)) reasons.push(`${today} is not an NSE trading day`);
  const mins = istMinutes(now);
  if (mins < hhmm(cfg.entryWindowStart) || mins > hhmm(cfg.entryWindowEnd)) {
    reasons.push(`outside the entry window ${cfg.entryWindowStart}-${cfg.entryWindowEnd} IST`);
  }

  // Data freshness.
  const dataAt = Date.parse(p.dataTimestamp);
  if (!Number.isFinite(dataAt)) reasons.push("data timestamp missing or invalid: DATA INSUFFICIENT");
  else {
    const age = (now.getTime() - dataAt) / 1000;
    if (age > cfg.maxQuoteAgeSec) reasons.push(`market data is ${Math.round(age)}s old (max ${cfg.maxQuoteAgeSec}s): DATA INSUFFICIENT`);
    if (age < -5) reasons.push("market data timestamp is in the future");
  }

  // Strategy.
  if (ctx.allowedStrategyIds && !ctx.allowedStrategyIds.has(p.strategyId)) {
    reasons.push(`strategy ${p.strategyId} is not ACCEPTED for live trading`);
  }

  // Instrument / product.
  if (inst.exchange !== "NSE") reasons.push("only NSE is supported");
  if (inst.segment === "FNO") {
    if (!cfg.allowDerivatives) reasons.push("derivatives are disabled (ALLOW_DERIVATIVES=false; project policy bans them)");
    if (inst.instrumentType === "EQ") reasons.push("FNO segment needs a FUT/CE/PE instrument");
    if (p.product === "CNC") reasons.push("CNC is not valid for FNO");
  } else {
    if (inst.instrumentType !== "EQ") reasons.push("CASH segment needs an EQ instrument");
    if (inst.lotSize !== 1) reasons.push("cash equity lot size must be 1");
    if (p.product === "NRML") reasons.push("NRML is not valid for CASH");
  }
  if (!long) {
    if (!cfg.allowShort) reasons.push("short selling is disabled (ALLOW_SHORT=false)");
    if (inst.segment === "CASH" && p.product !== "MIS") reasons.push("cash shorts must be intraday (MIS)");
  }
  if (!(inst.tickSize > 0) || !(inst.lotSize >= 1)) reasons.push("instrument tick size / lot size invalid");

  // Prices.
  const { price: entry, triggerPrice } = p.entry;
  for (const [name, v] of [["entry", entry], ["stop", p.stopLoss], ["target", p.target], ["reference", p.referencePrice]] as const) {
    if (!(v > 0) || !Number.isFinite(v)) reasons.push(`${name} price must be positive`);
    else if (inst.tickSize > 0 && name !== "reference" && !onTick(v, inst.tickSize)) reasons.push(`${name} price ${v} is not a multiple of tick ${inst.tickSize}`);
  }
  if (long && !(p.stopLoss < entry && entry < p.target)) reasons.push("long needs stop < entry < target");
  if (!long && !(p.stopLoss > entry && entry > p.target)) reasons.push("short needs target < entry < stop");
  if (p.entry.orderType === "SL") {
    if (!(triggerPrice && triggerPrice > 0)) reasons.push("SL entry needs a trigger price");
    else if (long ? triggerPrice > entry : triggerPrice < entry) reasons.push("SL entry trigger must not be beyond the limit price");
  }
  if (p.referencePrice > 0 && entry > 0) {
    const dev = (Math.abs(entry - p.referencePrice) / p.referencePrice) * 100;
    if (dev > cfg.maxEntryDeviationPct) reasons.push(`entry is ${dev.toFixed(2)}% from the last price (max ${cfg.maxEntryDeviationPct}%)`);
  }

  // Quantity.
  const qty = p.quantity;
  if (!Number.isInteger(qty) || qty <= 0) reasons.push("quantity must be a positive whole number");
  else if (qty % inst.lotSize !== 0) reasons.push(`quantity ${qty} is not a multiple of lot size ${inst.lotSize}`);

  // Portfolio.
  if (ctx.existingPositionQty !== 0) reasons.push(`already holding ${ctx.existingPositionQty} in ${inst.tradingSymbol}: no averaging or pyramiding`);
  if (ctx.dailySlotHolder && ctx.dailySlotHolder !== ctx.tradeId) reasons.push("today's one trade is already used");

  // Money.
  let metrics: RiskMetrics | null = null;
  const pricesUsable = entry > 0 && p.stopLoss > 0 && p.target > 0 && inst.tickSize > 0 && entry !== p.stopLoss;
  if (pricesUsable && Number.isInteger(qty) && qty > 0) {
    metrics = computeMetrics(p, qty, cfg, rates);
    if (metrics.plannedRiskInr > cfg.maxPlannedRiskInr + EPS) {
      reasons.push(`planned risk ₹${metrics.plannedRiskInr.toFixed(2)} (incl. slippage and charges) exceeds ₹${cfg.maxPlannedRiskInr}`);
    }
    if (inst.segment === "FNO") {
      const oneLot = computeMetrics(p, inst.lotSize, cfg, rates);
      if (oneLot.plannedRiskInr > cfg.maxPlannedRiskInr + EPS) reasons.push(`one lot risks ₹${oneLot.plannedRiskInr.toFixed(2)}, above the ₹${cfg.maxPlannedRiskInr} budget`);
    }
    if (metrics.rewardRiskNet + EPS < cfg.minRewardRisk) {
      reasons.push(`net reward:risk 1:${metrics.rewardRiskNet.toFixed(2)} after costs is below 1:${cfg.minRewardRisk}`);
    }
    if (metrics.notionalInr > cfg.maxNotionalInr + EPS) {
      reasons.push(`order value ₹${metrics.notionalInr.toFixed(0)} exceeds the cash cap ₹${cfg.maxNotionalInr} (no leverage)`);
    }
  }

  return { approved: reasons.length === 0, reasons, metrics, checkedAt: now.toISOString() };
}

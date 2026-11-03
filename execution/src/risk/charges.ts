import type { ChargeBreakdown, Instrument, Product, Side } from "../domain/types.js";

/**
 * Transaction-charge model for NSE trades through Groww.
 *
 * VERIFIED: false. These rates come from commonly published NSE/SEBI schedules and Groww's public pricing as
 * remembered, NOT from a document fetched on a known date (groww.in is blocked from the build environment).
 * Where a rate may have changed recently (F&O STT after the 2026 Budget) the HIGHER candidate is used, and
 * the risk engine adds CHARGES_SAFETY_BUFFER_PCT (default 25%) on top. Check every number against Groww's
 * pricing page and a real contract note before trusting the ₹ figures; see docs/UNVERIFIED.md.
 */
export interface ChargeRates {
  verified: boolean;
  source: string;
  brokeragePctEquity: number; // per executed order
  brokerageCapEquity: number;
  brokerageMinEquity: number;
  brokerageFlatFno: number;
  sttPct: { cashIntradaySell: number; cashDeliveryBoth: number; futSell: number; optSellPremium: number };
  exchangeTxnPct: { cash: number; fut: number; opt: number };
  sebiPct: number;
  stampBuyPct: { cashIntraday: number; cashDelivery: number; fut: number; opt: number };
  gstPct: number;
  dpChargePerSellDelivery: number;
}

export const DEFAULT_RATES: ChargeRates = Object.freeze({
  verified: false,
  source: "Unverified placeholders (2026-11-03); conservative where unsure. Verify against Groww pricing + a contract note.",
  brokeragePctEquity: 0.1,
  brokerageCapEquity: 20,
  brokerageMinEquity: 5,
  brokerageFlatFno: 20,
  sttPct: { cashIntradaySell: 0.025, cashDeliveryBoth: 0.1, futSell: 0.05, optSellPremium: 0.15 },
  exchangeTxnPct: { cash: 0.00297, fut: 0.00173, opt: 0.03503 },
  sebiPct: 0.0001,
  stampBuyPct: { cashIntraday: 0.003, cashDelivery: 0.015, fut: 0.002, opt: 0.003 },
  gstPct: 18,
  dpChargePerSellDelivery: 20,
}) as ChargeRates;

const pct = (value: number, p: number) => (value * p) / 100;

/** Charges for one executed leg. */
export function legCharges(
  inst: Instrument,
  product: Product,
  side: Side,
  price: number,
  quantity: number,
  rates: ChargeRates = DEFAULT_RATES,
): Omit<ChargeBreakdown, "safetyBuffer" | "total"> {
  const value = price * quantity;
  const isCash = inst.segment === "CASH";
  const isOpt = inst.instrumentType === "CE" || inst.instrumentType === "PE";
  const delivery = isCash && product === "CNC";

  const brokerage = isCash
    ? Math.max(rates.brokerageMinEquity, Math.min(rates.brokerageCapEquity, pct(value, rates.brokeragePctEquity)))
    : rates.brokerageFlatFno;

  let stt = 0;
  if (isCash) stt = delivery ? pct(value, rates.sttPct.cashDeliveryBoth) : side === "SELL" ? pct(value, rates.sttPct.cashIntradaySell) : 0;
  else if (isOpt) stt = side === "SELL" ? pct(value, rates.sttPct.optSellPremium) : 0;
  else stt = side === "SELL" ? pct(value, rates.sttPct.futSell) : 0;

  const exchangeTxn = pct(value, isCash ? rates.exchangeTxnPct.cash : isOpt ? rates.exchangeTxnPct.opt : rates.exchangeTxnPct.fut);
  const sebiFee = pct(value, rates.sebiPct);
  const stampDuty =
    side === "BUY"
      ? pct(value, isCash ? (delivery ? rates.stampBuyPct.cashDelivery : rates.stampBuyPct.cashIntraday) : isOpt ? rates.stampBuyPct.opt : rates.stampBuyPct.fut)
      : 0;
  const gst = pct(brokerage + exchangeTxn + sebiFee, rates.gstPct);
  const dpCharge = delivery && side === "SELL" ? rates.dpChargePerSellDelivery : 0;
  return { brokerage, stt, exchangeTxn, sebiFee, stampDuty, gst, dpCharge };
}

/** Round trip: entry leg plus exit leg, with the safety buffer applied to the total. */
export function roundTripCharges(
  inst: Instrument,
  product: Product,
  entrySide: Side,
  entryPrice: number,
  exitPrice: number,
  quantity: number,
  safetyBufferPct: number,
  rates: ChargeRates = DEFAULT_RATES,
): ChargeBreakdown {
  const exitSide: Side = entrySide === "BUY" ? "SELL" : "BUY";
  const a = legCharges(inst, product, entrySide, entryPrice, quantity, rates);
  const b = legCharges(inst, product, exitSide, exitPrice, quantity, rates);
  const sum = {
    brokerage: a.brokerage + b.brokerage,
    stt: a.stt + b.stt,
    exchangeTxn: a.exchangeTxn + b.exchangeTxn,
    sebiFee: a.sebiFee + b.sebiFee,
    stampDuty: a.stampDuty + b.stampDuty,
    gst: a.gst + b.gst,
    dpCharge: a.dpCharge + b.dpCharge,
  };
  const base = Object.values(sum).reduce((x, y) => x + y, 0);
  const safetyBuffer = pct(base, safetyBufferPct);
  return { ...sum, safetyBuffer, total: base + safetyBuffer };
}

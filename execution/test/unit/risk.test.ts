import { describe, expect, it } from "vitest";
import { legCharges, roundTripCharges } from "../../src/risk/charges.js";
import { computeMetrics, maxQuantity, validate, type RiskContext } from "../../src/risk/riskEngine.js";
import { DAY, T0, proposal, testConfig } from "../helpers/fixtures.js";

const cfg = testConfig().risk;
const ctx = (over: Partial<RiskContext> = {}): RiskContext => ({
  now: T0,
  mode: "PAPER",
  killSwitch: false,
  halted: false,
  existingPositionQty: 0,
  dailySlotHolder: null,
  ...over,
});

describe("charges", () => {
  const eq = proposal().instrument;
  it("caps equity brokerage at ₹20 and floors it at ₹5", () => {
    expect(legCharges(eq, "MIS", "BUY", 1000, 100).brokerage).toBe(20); // 0.1% of 1,00,000 = 100 -> 20
    expect(legCharges(eq, "MIS", "BUY", 100, 1).brokerage).toBe(5); // 0.1 -> min 5
  });
  it("charges intraday STT on the sell leg only and stamp duty on the buy leg only", () => {
    const buy = legCharges(eq, "MIS", "BUY", 1000, 10);
    const sell = legCharges(eq, "MIS", "SELL", 1000, 10);
    expect(buy.stt).toBe(0);
    expect(sell.stt).toBeCloseTo(2.5, 6); // 0.025% of 10,000
    expect(buy.stampDuty).toBeCloseTo(0.3, 6);
    expect(sell.stampDuty).toBe(0);
  });
  it("adds the safety buffer on top of the round trip", () => {
    const c0 = roundTripCharges(eq, "MIS", "BUY", 1000, 1010, 10, 0);
    const c25 = roundTripCharges(eq, "MIS", "BUY", 1000, 1010, 10, 25);
    expect(c25.total).toBeCloseTo(c0.total * 1.25, 6);
  });
});

describe("risk engine", () => {
  it("approves a clean setup and reports planned risk including slippage and charges", () => {
    const d = validate(proposal(), ctx(), cfg);
    expect(d.reasons).toEqual([]);
    expect(d.approved).toBe(true);
    const m = d.metrics!;
    expect(m.grossRiskInr).toBe(120);
    expect(m.plannedRiskInr).toBeGreaterThan(m.grossRiskInr + m.slippageInr);
    expect(m.plannedRiskInr).toBeLessThanOrEqual(300);
  });

  it("rejects when costs push planned risk over ₹300 even though gross risk is under", () => {
    // 29 shares x 10 = ₹290 gross; slippage + charges push it over 300.
    const d = validate(proposal({ quantity: 29 }), ctx(), testConfig({ MAX_NOTIONAL_INR: "100000" }).risk);
    expect(d.approved).toBe(false);
    expect(d.reasons.join()).toMatch(/planned risk/);
  });

  it("rejects reward:risk below 1:2 after costs", () => {
    const d = validate(proposal({ target: 1020 }), ctx(), cfg); // 2R gross, < 2R net
    expect(d.approved).toBe(false);
    expect(d.reasons.join()).toMatch(/reward:risk/);
  });

  it("rejects stale data as DATA INSUFFICIENT", () => {
    const d = validate(proposal({ dataTimestamp: new Date(T0.getTime() - 120_000).toISOString() }), ctx(), cfg);
    expect(d.reasons.join()).toMatch(/DATA INSUFFICIENT/);
  });

  it("rejects a second trade on the same day", () => {
    const d = validate(proposal(), ctx({ dailySlotHolder: "other-trade", tradeId: "this-trade" }), cfg);
    expect(d.reasons.join()).toMatch(/one trade is already used/);
    expect(validate(proposal(), ctx({ dailySlotHolder: "this-trade", tradeId: "this-trade" }), cfg).approved).toBe(true);
  });

  it("rejects averaging: an existing position in the symbol", () => {
    expect(validate(proposal(), ctx({ existingPositionQty: 5 }), cfg).reasons.join()).toMatch(/no averaging/);
  });

  it("rejects outside the entry window, on weekends and holidays", () => {
    expect(validate(proposal(), ctx({ now: new Date("2026-11-04T09:30:00Z") }), cfg).reasons.join()).toMatch(/entry window/); // 15:00 IST
    const sat = new Date("2026-11-07T04:30:00Z");
    expect(validate(proposal({ tradingDay: "2026-11-07", dataTimestamp: sat.toISOString() }), ctx({ now: sat }), cfg).reasons.join()).toMatch(/not an NSE trading day/);
    expect(validate(proposal(), ctx(), testConfig({ NSE_HOLIDAYS: DAY }).risk).reasons.join()).toMatch(/not an NSE trading day/);
  });

  it("rejects leverage: order value above the cash cap", () => {
    const p = proposal({ entry: { orderType: "LIMIT", price: 5000 }, stopLoss: 4990, target: 5050, referencePrice: 5000, quantity: 10 });
    expect(validate(p, ctx(), cfg).reasons.join()).toMatch(/cash cap/);
  });

  it("rejects derivatives by default and any lot whose single-lot risk exceeds the budget", () => {
    const fut = proposal({
      instrument: { tradingSymbol: "NIFTY26NOVFUT", exchange: "NSE", segment: "FNO", instrumentType: "FUT", lotSize: 75, tickSize: 0.05 },
      product: "NRML",
      quantity: 75,
    });
    expect(validate(fut, ctx(), cfg).reasons.join()).toMatch(/derivatives are disabled/);
    const allow = testConfig({ ALLOW_DERIVATIVES: "true", MAX_NOTIONAL_INR: "10000000" }).risk;
    expect(validate(fut, ctx(), allow).reasons.join()).toMatch(/one lot risks/);
  });

  it("rejects wrong-side stops and targets, off-tick prices, bad quantities", () => {
    expect(validate(proposal({ stopLoss: 1005 }), ctx(), cfg).reasons.join()).toMatch(/stop < entry < target/);
    expect(validate(proposal({ stopLoss: 990.02 }), ctx(), cfg).reasons.join()).toMatch(/tick/);
    expect(validate(proposal({ quantity: 2.5 }), ctx(), cfg).reasons.join()).toMatch(/whole number/);
    expect(validate(proposal({ quantity: 0 }), ctx(), cfg).reasons.join()).toMatch(/whole number/);
  });

  it("rejects shorts unless enabled, and cash shorts outside MIS", () => {
    const s = proposal({ direction: "SHORT", stopLoss: 1010, target: 960 });
    expect(validate(s, ctx(), cfg).reasons.join()).toMatch(/short selling is disabled/);
    const on = testConfig({ ALLOW_SHORT: "true" }).risk;
    expect(validate(s, ctx(), on).approved).toBe(true);
    expect(validate({ ...s, product: "CNC" }, ctx(), on).reasons.join()).toMatch(/MIS/);
  });

  it("enforces the live strategy allow-list and the kill switch", () => {
    expect(validate(proposal(), ctx({ allowedStrategyIds: new Set(["EXP-9999"]) }), cfg).reasons.join()).toMatch(/not ACCEPTED/);
    expect(validate(proposal(), ctx({ killSwitch: true }), cfg).reasons.join()).toMatch(/kill switch/);
    expect(validate(proposal(), ctx({ halted: true }), cfg).reasons.join()).toMatch(/halted/);
  });

  it("maxQuantity returns the largest size inside the cap, and 0 when one unit does not fit", () => {
    const q = maxQuantity(proposal(), cfg);
    expect(q).toBeGreaterThan(0);
    expect(computeMetrics(proposal(), q, cfg).plannedRiskInr).toBeLessThanOrEqual(300);
    expect(computeMetrics(proposal(), q + 1, cfg).plannedRiskInr > 300 || computeMetrics(proposal(), q + 1, cfg).notionalInr > cfg.maxNotionalInr).toBe(true);
    expect(maxQuantity(proposal({ stopLoss: 690, entry: { orderType: "LIMIT", price: 1000 } }), cfg)).toBe(0);
  });
});

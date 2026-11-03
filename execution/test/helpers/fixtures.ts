import { loadConfig, type AppConfig } from "../../src/config/config.js";
import type { TradeProposal } from "../../src/domain/types.js";

/** 2026-11-04 (Wednesday) 10:00 IST. */
export const T0 = new Date("2026-11-04T04:30:00.000Z");
export const DAY = "2026-11-04";

export function testConfig(overrides: Record<string, string> = {}): AppConfig {
  return loadConfig({ EXECUTION_MODE: "PAPER", OCO_POLL_INTERVAL_MS: "1", OCO_CONFIRM_TIMEOUT_SEC: "5", ...overrides });
}

/**
 * A synthetic long setup (NOT market data): entry 1000, stop 990, target 1040.
 * Per-share risk 10; a 4R gross target, because at this size charges and slippage turn 3R into ~1.7R net.
 */
export function proposal(over: Partial<TradeProposal> = {}): TradeProposal {
  return {
    proposalId: "prop-1",
    strategyId: "EXP-TEST",
    tradingDay: DAY,
    instrument: { tradingSymbol: "TESTSTOCK", exchange: "NSE", segment: "CASH", instrumentType: "EQ", lotSize: 1, tickSize: 0.05 },
    direction: "LONG",
    product: "MIS",
    entry: { orderType: "LIMIT", price: 1000 },
    stopLoss: 990,
    target: 1040,
    quantity: 12,
    referencePrice: 999.5,
    dataTimestamp: new Date(T0.getTime() - 10_000).toISOString(),
    createdAt: T0.toISOString(),
    ...over,
  };
}

import type { TradeProposal } from "./types.js";

export class ProposalError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProposalError";
  }
}

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

function need<T>(cond: boolean, v: T, msg: string): T {
  if (!cond) throw new ProposalError(msg);
  return v;
}

/** Strict shape check for proposals arriving over the intake endpoint (from the Python scan). */
export function parseProposal(input: unknown): TradeProposal {
  if (!isObj(input)) throw new ProposalError("proposal must be a JSON object");
  const s = (k: string) => need(typeof input[k] === "string" && (input[k] as string).length > 0, input[k] as string, `${k} must be a non-empty string`);
  const n = (o: Record<string, unknown>, k: string) => need(typeof o[k] === "number" && Number.isFinite(o[k]), o[k] as number, `${k} must be a number`);
  const inst = need(isObj(input.instrument), input.instrument as Record<string, unknown>, "instrument must be an object");
  const entry = need(isObj(input.entry), input.entry as Record<string, unknown>, "entry must be an object");
  const oneOf = <T extends string>(v: unknown, allowed: readonly T[], k: string): T => need(typeof v === "string" && (allowed as readonly string[]).includes(v), v as T, `${k} must be one of ${allowed.join(", ")}`);

  const tradingDay = s("tradingDay");
  need(/^\d{4}-\d{2}-\d{2}$/.test(tradingDay), 0, "tradingDay must be YYYY-MM-DD");
  for (const k of ["dataTimestamp", "createdAt"]) need(Number.isFinite(Date.parse(s(k))), 0, `${k} must be an ISO timestamp`);

  return {
    proposalId: s("proposalId"),
    strategyId: s("strategyId"),
    tradingDay,
    instrument: {
      tradingSymbol: need(typeof inst.tradingSymbol === "string" && /^[A-Z0-9&_-]{1,40}$/.test(inst.tradingSymbol), inst.tradingSymbol as string, "instrument.tradingSymbol invalid"),
      exchange: oneOf(inst.exchange, ["NSE"] as const, "instrument.exchange"),
      segment: oneOf(inst.segment, ["CASH", "FNO"] as const, "instrument.segment"),
      instrumentType: oneOf(inst.instrumentType, ["EQ", "FUT", "CE", "PE"] as const, "instrument.instrumentType"),
      lotSize: n(inst, "lotSize"),
      tickSize: n(inst, "tickSize"),
      underlying: typeof inst.underlying === "string" ? inst.underlying : undefined,
      expiry: typeof inst.expiry === "string" ? inst.expiry : undefined,
    },
    direction: oneOf(input.direction, ["LONG", "SHORT"] as const, "direction"),
    product: oneOf(input.product, ["MIS", "CNC", "NRML"] as const, "product"),
    entry: {
      orderType: oneOf(entry.orderType, ["LIMIT", "SL"] as const, "entry.orderType"),
      price: n(entry, "price"),
      triggerPrice: entry.triggerPrice === undefined ? undefined : n(entry, "triggerPrice"),
    },
    stopLoss: n(input, "stopLoss"),
    target: n(input, "target"),
    quantity: n(input, "quantity"),
    referencePrice: n(input, "referencePrice"),
    dataTimestamp: input.dataTimestamp as string,
    createdAt: input.createdAt as string,
    notes: typeof input.notes === "string" ? input.notes.slice(0, 500) : undefined,
  };
}

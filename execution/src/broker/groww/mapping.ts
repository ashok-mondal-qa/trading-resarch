import type { Fill, NormalizedOrderStatus, OcoSnapshot, OrderSnapshot, ProtectionStatus } from "../../domain/types.js";
import { BrokerShapeError } from "../BrokerPort.js";

/**
 * Translation between Groww payloads and engine types. Every field read here is listed in docs/UNVERIFIED.md
 * with where it came from. Endpoint paths and request bodies come from Groww's official Python SDK 1.5.0;
 * RESPONSE field names below are NOT in that SDK and come from memory of Groww's docs, so the parsers are
 * strict: a missing field throws BrokerShapeError, which the engine treats as UNKNOWN (no state advance,
 * no assumed fill, no assumed protection). Run `npm run groww:probe` on the deployment machine to check them.
 */

type Obj = Record<string, unknown>;

function obj(v: unknown, what: string): Obj {
  if (!v || typeof v !== "object" || Array.isArray(v)) throw new BrokerShapeError(`${what}: expected an object`);
  return v as Obj;
}
function str(o: Obj, k: string, what: string): string {
  const v = o[k];
  if (typeof v !== "string" || !v) throw new BrokerShapeError(`${what}: missing string field ${k}`);
  return v;
}
function numField(o: Obj, k: string, what: string): number {
  const v = typeof o[k] === "string" ? Number(o[k]) : o[k];
  if (typeof v !== "number" || !Number.isFinite(v)) throw new BrokerShapeError(`${what}: missing numeric field ${k}`);
  return v;
}
function optNum(o: Obj, k: string): number | undefined {
  const v = typeof o[k] === "string" ? Number(o[k]) : o[k];
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}
function arr(o: Obj, k: string, what: string): unknown[] {
  const v = o[k];
  if (!Array.isArray(v)) throw new BrokerShapeError(`${what}: missing array field ${k}`);
  return v;
}

/** Groww order_status values as remembered from the docs (UNVERIFIED). Anything else maps to UNKNOWN. */
const PENDING_RAW = new Set(["NEW", "ACKED", "OPEN", "TRIGGER_PENDING", "APPROVED", "MODIFICATION_REQUESTED", "CANCELLATION_REQUESTED"]);
const DONE_RAW = new Set(["EXECUTED", "COMPLETED", "DELIVERY_AWAITED"]);
const REJECTED_RAW = new Set(["REJECTED", "FAILED"]);
const CANCELLED_RAW = new Set(["CANCELLED"]);

export function normalizeOrderStatus(raw: string, ordered: number, filled: number): NormalizedOrderStatus {
  const s = raw.toUpperCase();
  if (DONE_RAW.has(s)) return filled >= ordered && ordered > 0 ? "FILLED" : filled > 0 ? "PARTIALLY_FILLED" : "UNKNOWN";
  if (PENDING_RAW.has(s)) return filled > 0 ? "PARTIALLY_FILLED" : "PENDING";
  if (CANCELLED_RAW.has(s)) return "CANCELLED";
  if (REJECTED_RAW.has(s)) return "REJECTED";
  return "UNKNOWN";
}

/** GET /order/detail/{id}?segment= */
export function parseOrderDetail(payload: unknown): OrderSnapshot {
  const o = obj(payload, "order detail");
  const raw = str(o, "order_status", "order detail");
  const ordered = numField(o, "quantity", "order detail");
  const filled = numField(o, "filled_quantity", "order detail");
  return {
    brokerOrderId: str(o, "groww_order_id", "order detail"),
    clientRef: typeof o.order_reference_id === "string" ? o.order_reference_id : undefined,
    status: normalizeOrderStatus(raw, ordered, filled),
    rawStatus: raw,
    orderedQuantity: ordered,
    reportedFilledQuantity: filled,
    averageFillPrice: optNum(o, "average_fill_price"),
    remark: typeof o.remark === "string" ? o.remark : undefined,
  };
}

/** POST /order/create response. Only the id and status are trusted; acceptance is not a fill. */
export function parseOrderAck(payload: unknown): { brokerOrderId: string; rawStatus: string } {
  const o = obj(payload, "order create");
  return { brokerOrderId: str(o, "groww_order_id", "order create"), rawStatus: str(o, "order_status", "order create") };
}

/** GET /order/status/reference/{ref}?segment= : returns the Groww order id for our reference. */
export function parseOrderIdByRef(payload: unknown): string {
  return str(obj(payload, "order status by reference"), "groww_order_id", "order status by reference");
}

/** GET /order/trades/{id}?segment=&page=&page_size= */
export function parseTrades(payload: unknown, brokerOrderId: string): Fill[] {
  const o = obj(payload, "trade list");
  return arr(o, "trade_list", "trade list").map((t, i) => {
    const r = obj(t, `trade ${i}`);
    const id = typeof r.groww_trade_id === "string" ? r.groww_trade_id : typeof r.exchange_trade_id === "string" ? r.exchange_trade_id : undefined;
    if (!id) throw new BrokerShapeError(`trade ${i}: missing trade id`);
    return {
      brokerTradeId: id,
      brokerOrderId,
      quantity: numField(r, "quantity", `trade ${i}`),
      price: numField(r, "price", `trade ${i}`),
      at: typeof r.trade_date_time === "string" ? r.trade_date_time : typeof r.created_at === "string" ? r.created_at : "",
    };
  });
}

/**
 * GET /positions/trading-symbol?trading_symbol=&segment= -> { positions: [...] }.
 * Net quantity is summed over every product row for the symbol, so a CNC holding and an MIS position both
 * count (the risk engine refuses entries while any exist).
 */
export function parsePositionQty(payload: unknown, symbol: string): number {
  const o = obj(payload, "positions");
  const rows = arr(o, "positions", "positions");
  let net = 0;
  for (const [i, row] of rows.entries()) {
    const r = obj(row, `position ${i}`);
    if (r.trading_symbol !== undefined && r.trading_symbol !== symbol) continue;
    net += numField(r, "quantity", `position ${i}`);
  }
  return net;
}

const SMART_STATUS: Record<string, ProtectionStatus> = {
  ACTIVE: "ACTIVE",
  TRIGGERED: "TRIGGERED",
  CANCELLED: "CANCELLED",
  EXPIRED: "EXPIRED",
  FAILED: "FAILED",
  COMPLETED: "COMPLETED",
};

/** Smart-order status values are VERIFIED from the SDK constants; the field names are not. */
export function parseSmartOrder(payload: unknown): OcoSnapshot {
  const o = obj(payload, "smart order");
  const raw = str(o, "status", "smart order");
  return {
    brokerOcoId: str(o, "smart_order_id", "smart order"),
    clientRef: typeof o.reference_id === "string" ? o.reference_id : undefined,
    status: SMART_STATUS[raw.toUpperCase()] ?? "UNKNOWN",
    rawStatus: raw,
    quantity: numField(o, "quantity", "smart order"),
    remark: typeof o.remark === "string" ? o.remark : typeof o.message === "string" ? o.message : undefined,
  };
}

/** GET /order-advance/list -> list of smart orders under `orders` (UNVERIFIED key). */
export function parseSmartOrderList(payload: unknown): OcoSnapshot[] {
  return arr(obj(payload, "smart order list"), "orders", "smart order list").map(parseSmartOrder);
}

/** GET /live-data/quote?exchange=&segment=&trading_symbol= -> last_price and last_trade_time (epoch ms). */
export function parseQuote(payload: unknown): { price: number; at: string } {
  const o = obj(payload, "quote");
  const price = numField(o, "last_price", "quote");
  const t = numField(o, "last_trade_time", "quote");
  const ms = t < 1e12 ? t * 1000 : t;
  return { price, at: new Date(ms).toISOString() };
}

/** Prices go out as decimal strings for smart orders (the SDK documents GTT trigger_price as a decimal string). */
export function priceStr(v: number): string {
  return v.toFixed(2);
}

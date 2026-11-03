import { GrowwTokenManager } from "../broker/groww/auth.js";
import { GrowwHttp, type HttpFetch } from "../broker/groww/http.js";
import { parsePositionQty, parseQuote, parseSmartOrderList, parseTrades } from "../broker/groww/mapping.js";
import { loadConfig } from "../config/config.js";
import { systemClock } from "../util/clock.js";

/**
 * `npm run groww:probe -- <SYMBOL> [ORDER_ID]` — READ-ONLY check of the response shapes this engine relies on.
 * Sends only GET requests (plus the token request). Prints field NAMES and types, never values, so the output
 * can be shared safely. Use it to tick off docs/UNVERIFIED.md before any live use.
 */
function shape(v: unknown, depth = 0): unknown {
  if (Array.isArray(v)) return v.length ? [shape(v[0], depth + 1)] : [];
  if (v && typeof v === "object" && depth < 4) return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, shape(x, depth + 1)]));
  return typeof v;
}

async function main() {
  const [symbol, orderId] = process.argv.slice(2);
  if (!symbol) throw new Error("usage: groww:probe <SYMBOL> [ORDER_ID]");
  const cfg = loadConfig().groww;
  const f = fetch as unknown as HttpFetch;
  const http = new GrowwHttp(cfg.baseUrl, new GrowwTokenManager(cfg, f, systemClock), f, cfg.requestTimeoutMs);
  const checks: [string, () => Promise<unknown>, (p: unknown) => unknown][] = [
    ["quote", () => http.get("/live-data/quote", { exchange: "NSE", segment: "CASH", trading_symbol: symbol }), parseQuote],
    ["position", () => http.get("/positions/trading-symbol", { trading_symbol: symbol, segment: "CASH" }), (p) => parsePositionQty(p, symbol)],
    ["smart order list", () => http.get("/order-advance/list", { smart_order_type: "OCO", segment: "CASH", page: 0, page_size: 5 }), parseSmartOrderList],
    ["order list", () => http.get("/order/list", { segment: "CASH", page: 0, page_size: 5 }), () => "n/a"],
  ];
  if (orderId) {
    checks.push(["order detail", () => http.get(`/order/detail/${orderId}`, { segment: "CASH" }), () => "see shape"]);
    checks.push(["trades", () => http.get(`/order/trades/${orderId}`, { segment: "CASH", page: 0, page_size: 5 }), (p) => parseTrades(p, orderId).length]);
  }
  for (const [name, call, parse] of checks) {
    try {
      const payload = await call();
      let parsed = "ok";
      try {
        parse(payload);
      } catch (e) {
        parsed = `MAPPING FAILED: ${(e as Error).message}`;
      }
      console.log(`\n## ${name}: ${parsed}\n${JSON.stringify(shape(payload), null, 2)}`);
    } catch (e) {
      console.log(`\n## ${name}: request failed: ${(e as Error).message}`);
    }
  }
}

main().catch((e) => {
  console.error((e as Error).message);
  process.exit(1);
});

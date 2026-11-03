import { createHash } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { BrokerError, BrokerRejectedError, BrokerShapeError, BrokerUncertainError } from "../../src/broker/BrokerPort.js";
import { GrowwBroker, LiveOrdersDisabled } from "../../src/broker/groww/GrowwBroker.js";
import { GrowwTokenManager, base32Decode, lastTokenReset, totp } from "../../src/broker/groww/auth.js";
import { GrowwHttp, type HttpFetch } from "../../src/broker/groww/http.js";
import { loadConfig } from "../../src/config/config.js";
import { FakeClock } from "../../src/util/clock.js";
import { T0, proposal } from "../helpers/fixtures.js";
import { MockGroww, failure, ok } from "../helpers/mockGroww.js";

const API_KEY = "test-api-key-value";
const API_SECRET = "test-api-secret-value";

let mock: MockGroww;
let clock: FakeClock;

function build(env: Record<string, string> = {}, timeoutMs = 2000) {
  const cfg = loadConfig({ GROWW_BASE_URL: mock.base, GROWW_API_KEY: API_KEY, GROWW_API_SECRET: API_SECRET, GROWW_TIMEOUT_MS: String(timeoutMs), ...env }).groww;
  const f = fetch as unknown as HttpFetch;
  const tokens = new GrowwTokenManager(cfg, f, clock);
  const http = new GrowwHttp(cfg.baseUrl, tokens, f, cfg.requestTimeoutMs);
  return { tokens, http, broker: new GrowwBroker(http) };
}

beforeEach(async () => {
  mock = await new MockGroww().start();
  clock = new FakeClock(T0);
  mock.on((r) => (r.path === "/token/api/access" ? { status: 200, body: { token: "ACCESS-1" } } : undefined));
});
afterEach(async () => {
  await mock.stop();
});

describe("Groww auth", () => {
  it("RFC 6238 TOTP test vector", () => {
    const key = Buffer.from("12345678901234567890");
    expect(totp(key, new Date(59_000), 8)).toBe("94287082");
    expect(totp(key, new Date(1_111_111_109_000), 8)).toBe("07081804");
    expect(base32Decode("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ").toString()).toBe("12345678901234567890");
  });

  it("uses the approval-key checksum flow and caches the token until the 06:00 IST reset", async () => {
    const { tokens } = build();
    expect(await tokens.token()).toBe("ACCESS-1");
    expect(await tokens.token()).toBe("ACCESS-1");
    const calls = mock.calls.filter((c) => c.path === "/token/api/access");
    expect(calls).toHaveLength(1);
    const body = calls[0]!.body as { key_type: string; checksum: string; timestamp: number };
    expect(body.key_type).toBe("approval");
    expect(body.checksum).toBe(createHash("sha256").update(API_SECRET + String(body.timestamp)).digest("hex"));
    expect(calls[0]!.headers.authorization).toBe(`Bearer ${API_KEY}`);
    expect(JSON.stringify(body)).not.toContain(API_SECRET);

    clock.set("2026-11-05T00:31:00Z"); // 06:01 IST next day
    await tokens.token();
    expect(mock.calls.filter((c) => c.path === "/token/api/access")).toHaveLength(2);
    expect(new Date(lastTokenReset(new Date("2026-11-04T00:00:00Z"))).toISOString()).toBe("2026-11-03T00:30:00.000Z");
  });

  it("refreshes once on 401 and retries the request", async () => {
    let n = 0;
    mock.on((r) => (r.path.startsWith("/order/detail/") ? (++n === 1 ? { status: 401, body: {} } : ok({ groww_order_id: "G1", order_status: "ACKED", quantity: 10, filled_quantity: 0 })) : undefined));
    const { broker } = build();
    expect((await broker.getOrder("G1", "CASH")).status).toBe("PENDING");
    expect(mock.calls.filter((c) => c.path === "/token/api/access")).toHaveLength(2);
  });

  it("does not leak credentials in auth errors", async () => {
    mock.on((r) => (r.path === "/token/api/access" ? { status: 403, body: {} } : undefined));
    const { tokens } = build();
    const err = await tokens.token().catch((e: Error) => e);
    expect(String((err as Error).message)).not.toMatch(new RegExp(`${API_KEY}|${API_SECRET}`));
  });
});

describe("Groww reads", () => {
  it("maps order detail: accepted is PENDING, partial is PARTIALLY_FILLED, executed is FILLED", async () => {
    let filled = 0;
    let status = "ACKED";
    mock.on((r) => (r.path === "/order/detail/G1" ? ok({ groww_order_id: "G1", order_status: status, quantity: 12, filled_quantity: filled, average_fill_price: 1000, order_reference_id: "EREF" }) : undefined));
    const { broker } = build();
    expect((await broker.getOrder("G1", "CASH")).status).toBe("PENDING");
    filled = 5;
    expect((await broker.getOrder("G1", "CASH")).status).toBe("PARTIALLY_FILLED");
    filled = 12;
    status = "EXECUTED";
    expect((await broker.getOrder("G1", "CASH")).status).toBe("FILLED");
    status = "SOMETHING_NEW";
    expect((await broker.getOrder("G1", "CASH")).status).toBe("UNKNOWN");
    expect(mock.calls.at(-1)!.query.get("segment")).toBe("CASH");
  });

  it("finds an order by reference, and returns null when Groww says not found", async () => {
    mock.on((r) => (r.path === "/order/status/reference/EREF" ? ok({ groww_order_id: "G9", order_status: "ACKED" }) : undefined));
    mock.on((r) => (r.path === "/order/detail/G9" ? ok({ groww_order_id: "G9", order_status: "ACKED", quantity: 1, filled_quantity: 0 }) : undefined));
    const { broker } = build();
    expect((await broker.findOrderByClientRef("EREF", "CASH"))!.brokerOrderId).toBe("G9");
    expect(await broker.findOrderByClientRef("OTHER", "CASH")).toBeNull();
  });

  it("sums fills from the trade list across pages", async () => {
    mock.on((r) => {
      if (!r.path.startsWith("/order/trades/")) return undefined;
      const page = Number(r.query.get("page"));
      const rows = page === 0 ? Array.from({ length: 50 }, (_, i) => ({ groww_trade_id: `T${i}`, quantity: 1, price: 100 })) : [{ groww_trade_id: "T50", quantity: 2, price: 101 }];
      return ok({ trade_list: rows });
    });
    const { broker } = build();
    const fills = await broker.listFills("G1", "CASH");
    expect(fills.reduce((s, f) => s + f.quantity, 0)).toBe(52);
  });

  it("reads the net position across product rows for the symbol", async () => {
    mock.on((r) => (r.path === "/positions/trading-symbol" ? ok({ positions: [{ trading_symbol: "TESTSTOCK", quantity: 5, product: "MIS" }, { trading_symbol: "TESTSTOCK", quantity: 2, product: "CNC" }] }) : undefined));
    const { broker } = build();
    expect((await broker.getPosition("TESTSTOCK", "CASH")).netQuantity).toBe(7);
  });

  it("reads OCO status and refuses to guess when the shape is unexpected", async () => {
    mock.on((r) => (r.path === "/order-advance/status/CASH/OCO/internal/oco_1" ? ok({ smart_order_id: "oco_1", status: "ACTIVE", quantity: 12, reference_id: "OREF" }) : undefined));
    mock.on((r) => (r.path === "/order-advance/status/CASH/OCO/internal/oco_bad" ? ok({ id: "oco_bad", state: "ACTIVE" }) : undefined));
    const { broker } = build();
    expect(await broker.getOco("oco_1", "CASH")).toMatchObject({ status: "ACTIVE", quantity: 12 });
    await expect(broker.getOco("oco_bad", "CASH")).rejects.toBeInstanceOf(BrokerShapeError);
  });

  it("finds an OCO by reference, and errors (not 'not found') when references are missing from the list", async () => {
    let rows: unknown[] = [{ smart_order_id: "oco_1", status: "ACTIVE", quantity: 12, reference_id: "OREF" }];
    mock.on((r) => (r.path === "/order-advance/list" ? ok({ orders: rows }) : undefined));
    const { broker } = build();
    expect((await broker.findOcoByClientRef("OREF", "CASH"))!.brokerOcoId).toBe("oco_1");
    expect(await broker.findOcoByClientRef("NOPE", "CASH")).toBeNull();
    rows = [{ smart_order_id: "oco_1", status: "ACTIVE", quantity: 12 }];
    await expect(broker.findOcoByClientRef("OREF", "CASH")).rejects.toBeInstanceOf(BrokerShapeError);
  });

  it("reads a quote with its exchange timestamp", async () => {
    mock.on((r) => (r.path === "/live-data/quote" ? ok({ last_price: 999.5, last_trade_time: T0.getTime() }) : undefined));
    const { broker } = build();
    expect(await broker.getLtp(proposal().instrument)).toEqual({ price: 999.5, at: T0.toISOString() });
    expect(mock.calls.at(-1)!.query.get("trading_symbol")).toBe("TESTSTOCK");
  });
});

describe("Groww error classes", () => {
  it("reads: timeout is a plain BrokerError; writes: timeout and 5xx are UNCERTAIN, FAILURE 400 is REJECTED", async () => {
    mock.on((r) => (r.path === "/slow" ? { delayMs: 500, body: {} } : undefined));
    mock.on((r) => (r.path === "/boom" ? { status: 502, raw: "<html>bad gateway</html>" } : undefined));
    mock.on((r) => (r.path === "/no" ? failure(400, "GA001", "Insufficient margin") : undefined));
    mock.on((r) => (r.path === "/busy" ? failure(429, "429", "rate limited") : undefined));
    const { http } = build({}, 200);
    const read = await http.get("/slow").catch((e) => e);
    expect(read).toBeInstanceOf(BrokerError);
    expect(read).not.toBeInstanceOf(BrokerUncertainError);
    await expect(http.write("POST", "/slow", {})).rejects.toBeInstanceOf(BrokerUncertainError);
    await expect(http.write("POST", "/boom", {})).rejects.toBeInstanceOf(BrokerUncertainError);
    await expect(http.write("POST", "/busy", {})).rejects.toBeInstanceOf(BrokerUncertainError);
    const no = await http.write("POST", "/no", {}).catch((e) => e);
    expect(no).toBeInstanceOf(BrokerRejectedError);
    expect((no as Error).message).toMatch(/Insufficient margin/);
  });

  it("the default Groww broker cannot place anything", async () => {
    const { broker } = build();
    await expect(broker.submitOrder({ clientRef: "E1", instrument: proposal().instrument, side: "BUY", product: "MIS", orderType: "LIMIT", quantity: 1, price: 1, validity: "DAY" })).rejects.toBeInstanceOf(LiveOrdersDisabled);
    await expect(broker.cancelOco("x", "CASH")).rejects.toBeInstanceOf(LiveOrdersDisabled);
    expect(mock.calls.filter((c) => c.method !== "GET" && c.path !== "/token/api/access")).toHaveLength(0);
  });
});

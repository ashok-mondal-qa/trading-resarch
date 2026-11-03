import { spawn, type ChildProcess } from "node:child_process";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

/**
 * Boots the real composition root (dist/main.js) in PAPER mode against a fake Telegram Bot API and posts a
 * proposal to the intake endpoint. Checks the wiring end to end: intake auth -> risk engine -> Telegram.
 * Requires `npm run build` first (skipped otherwise).
 */
const root = fileURLToPath(new URL("../..", import.meta.url));
const mainJs = `${root}dist/main.js`;
const { existsSync } = await import("node:fs");

const BOT_TOKEN = "999:FAKE-BOT-TOKEN-FOR-TEST";
const INTAKE_TOKEN = "intake-test-token-123";

describe.skipIf(!existsSync(mainJs))("process smoke test (PAPER, fake Telegram)", () => {
  let tg: Server;
  let proc: ChildProcess;
  const sent: { method: string; body: Record<string, unknown>; url: string }[] = [];
  const port = 18000 + Math.floor(Math.random() * 1000);
  let logs = "";

  beforeAll(async () => {
    tg = createServer(async (req, res) => {
      const chunks: Buffer[] = [];
      for await (const c of req) chunks.push(c as Buffer);
      const method = (req.url ?? "").split("/").pop()!;
      const body = JSON.parse(Buffer.concat(chunks).toString() || "{}") as Record<string, unknown>;
      sent.push({ method, body, url: req.url ?? "" });
      const result = method === "getUpdates" ? [] : { message_id: sent.length };
      if (method === "getUpdates") await new Promise((r) => setTimeout(r, 200));
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, result }));
    });
    await new Promise<void>((r) => tg.listen(0, "127.0.0.1", r));
    const tgBase = `http://127.0.0.1:${(tg.address() as AddressInfo).port}`;
    proc = spawn(process.execPath, [mainJs], {
      cwd: root,
      env: {
        PATH: process.env.PATH,
        EXECUTION_MODE: "PAPER",
        ALLOW_MEMORY_STORE: "true",
        TELEGRAM_API_BASE: tgBase,
        TELEGRAM_BOT_TOKEN: BOT_TOKEN,
        TELEGRAM_ALLOWED_CHAT_ID: "100",
        TELEGRAM_ALLOWED_USER_IDS: "7",
        TELEGRAM_POLL_TIMEOUT_SEC: "1",
        INTAKE_TOKEN,
        INTAKE_PORT: String(port),
        RECONCILE_INTERVAL_MS: "200",
      },
    });
    proc.stdout!.on("data", (d) => (logs += String(d)));
    proc.stderr!.on("data", (d) => (logs += String(d)));
    for (let i = 0; i < 50; i++) {
      const ok = await fetch(`http://127.0.0.1:${port}/health`).then((r) => r.ok, () => false);
      if (ok) return;
      await new Promise((r) => setTimeout(r, 100));
    }
    throw new Error(`engine did not start:\n${logs}`);
  });

  afterAll(async () => {
    proc?.kill("SIGTERM");
    await new Promise((r) => setTimeout(r, 300));
    proc?.kill("SIGKILL");
    tg?.closeAllConnections();
    await new Promise<void>((r) => tg.close(() => r()));
  });

  it("refuses unauthenticated intake and malformed proposals", async () => {
    const r1 = await fetch(`http://127.0.0.1:${port}/proposals`, { method: "POST", body: "{}" });
    expect(r1.status).toBe(401);
    const r2 = await fetch(`http://127.0.0.1:${port}/proposals`, { method: "POST", headers: { Authorization: `Bearer ${INTAKE_TOKEN}` }, body: JSON.stringify({ proposalId: "x" }) });
    expect(r2.status).toBe(400);
  });

  it("routes a proposal through the risk engine and reports to Telegram without leaking the token", async () => {
    const now = new Date();
    const day = new Date(now.getTime() + 330 * 60_000).toISOString().slice(0, 10);
    const proposal = {
      proposalId: "smoke-1",
      strategyId: "EXP-TEST",
      tradingDay: day,
      instrument: { tradingSymbol: "TESTSTOCK", exchange: "NSE", segment: "CASH", instrumentType: "EQ", lotSize: 1, tickSize: 0.05 },
      direction: "LONG",
      product: "MIS",
      entry: { orderType: "LIMIT", price: 1000 },
      stopLoss: 990,
      target: 1040,
      quantity: 12,
      referencePrice: 999.5,
      dataTimestamp: now.toISOString(),
      createdAt: now.toISOString(),
    };
    const r = await fetch(`http://127.0.0.1:${port}/proposals`, { method: "POST", headers: { Authorization: `Bearer ${INTAKE_TOKEN}` }, body: JSON.stringify(proposal) });
    expect(r.status).toBe(200);
    const body = (await r.json()) as { state: string };
    // Depending on the wall-clock time this is AWAITING_APPROVAL (inside 09:20-14:30 IST on a weekday) or
    // RISK_REJECTED (outside it). Either way Telegram must have been told, and nothing was sent to a broker.
    expect(["AWAITING_APPROVAL", "RISK_REJECTED"]).toContain(body.state);
    await new Promise((r) => setTimeout(r, 300));
    const msgs = sent.filter((s) => s.method === "sendMessage");
    expect(msgs.length).toBeGreaterThanOrEqual(2); // start-up notice + proposal outcome
    expect(msgs.every((m) => m.body.chat_id === 100)).toBe(true);
    expect(JSON.stringify(sent.map((s) => s.body))).not.toContain(BOT_TOKEN);
    expect(logs).not.toContain(BOT_TOKEN);
    expect(logs).not.toContain(INTAKE_TOKEN);
  });
});

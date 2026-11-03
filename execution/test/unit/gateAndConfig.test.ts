import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { inspect } from "node:util";
import { describe, expect, it } from "vitest";
import { ConfigError, loadConfig } from "../../src/config/config.js";
import { LIVE_ACK_PHRASE, acceptedStrategies, checkLiveGate, parseCsv, sourceHash } from "../../src/config/liveGate.js";
import { assertTransition, canTransition } from "../../src/domain/stateMachine.js";
import { MemoryStore } from "../../src/store/MemoryStore.js";
import { Secret, redact } from "../../src/util/secret.js";
import { T0 } from "../helpers/fixtures.js";

describe("config hard ceilings", () => {
  it("defaults to PAPER with live disabled and the brief's limits", () => {
    const c = loadConfig({});
    expect(c.mode).toBe("PAPER");
    expect(c.live.liveTradingEnabled).toBe(false);
    expect(c.risk.maxPlannedRiskInr).toBe(300);
    expect(c.risk.minRewardRisk).toBe(2);
    expect(c.risk.allowDerivatives).toBe(false);
  });
  it("refuses to loosen limits", () => {
    expect(() => loadConfig({ MAX_PLANNED_RISK_INR: "301" })).toThrow(ConfigError);
    expect(() => loadConfig({ MIN_REWARD_RISK: "1.5" })).toThrow(ConfigError);
    expect(() => loadConfig({ LIVE_MIN_PAPER_WORKFLOWS: "5" })).toThrow(ConfigError);
    expect(() => loadConfig({ APPROVAL_TTL_SEC: "3600" })).toThrow(ConfigError);
    expect(() => loadConfig({ EXECUTION_MODE: "LIVE" })).toThrow(ConfigError);
    expect(() => loadConfig({ ENTRY_WINDOW_END: "15:20" })).toThrow(ConfigError);
    expect(() => loadConfig({ LIVE_TRADING_ENABLED: "yes" })).toThrow(ConfigError);
  });
  it("allows tightening", () => {
    expect(loadConfig({ MAX_PLANNED_RISK_INR: "150" }).risk.maxPlannedRiskInr).toBe(150);
  });
  it("reads secrets from *_FILE and never prints them", () => {
    const dir = mkdtempSync(join(tmpdir(), "sec-"));
    writeFileSync(join(dir, "k"), "super-secret-value\n");
    const c = loadConfig({ GROWW_API_KEY_FILE: join(dir, "k"), TELEGRAM_BOT_TOKEN: "123:abc-token" });
    expect(c.groww.apiKey!.reveal()).toBe("super-secret-value");
    const printed = JSON.stringify(c) + inspect(c, { depth: 10 }) + String(c.groww.apiKey);
    expect(printed).not.toContain("super-secret-value");
    expect(printed).not.toContain("abc-token");
  });
});

describe("redaction", () => {
  it("redacts secret-looking keys, Secret objects and bearer strings", () => {
    const r = redact({ apiKey: "x", nested: { access_token: "y", ok: 1 }, s: new Secret("z"), h: "Bearer abc", list: [{ password: "p" }] });
    expect(JSON.stringify(r)).not.toMatch(/"x"|"y"|"z"|abc|"p"/);
    expect((r as { nested: { ok: number } }).nested.ok).toBe(1);
  });
});

describe("state machine", () => {
  it("allows the documented path and blocks shortcuts", () => {
    expect(canTransition("AWAITING_APPROVAL", "APPROVED")).toBe(true);
    expect(canTransition("PROPOSED", "ENTRY_SUBMITTING")).toBe(false); // no entry without approval
    expect(canTransition("AWAITING_APPROVAL", "ENTRY_SUBMITTING")).toBe(false);
    expect(canTransition("ENTRY_PENDING", "PROTECTED")).toBe(false); // protection needs confirmation
    expect(canTransition("POSITION_UNPROTECTED", "PROTECTED")).toBe(false);
    expect(canTransition("PROTECTION_PENDING", "PROTECTED")).toBe(true);
    expect(canTransition("CLOSED", "HALTED")).toBe(false);
    expect(canTransition("PROTECTED", "HALTED")).toBe(true);
    expect(() => assertTransition("RISK_REJECTED", "APPROVED")).toThrow(/Illegal/);
  });
});

describe("live gate", () => {
  const registry = 'experiment_id,date,strategy,status,notes\nEXP-0001,2026-10-22,a,REJECTED,"x, y"\nEXP-0100,2026-11-10,b,ACCEPTED,ok\n';

  it("parses the registry CSV including quoted commas", () => {
    expect(parseCsv(registry)[0]!.notes).toBe("x, y");
    expect([...acceptedStrategies(registry)]).toEqual(["EXP-0100"]);
  });

  it("the real registry has no ACCEPTED strategy today", async () => {
    const { readFileSync } = await import("node:fs");
    const csv = readFileSync(new URL("../../../experiments/registry.csv", import.meta.url), "utf8");
    expect(acceptedStrategies(csv).size).toBe(0);
  });

  function setup(over: Record<string, string> = {}) {
    const root = mkdtempSync(join(tmpdir(), "gate-"));
    mkdirSync(join(root, "src"));
    writeFileSync(join(root, "src", "a.ts"), "export const a = 1;\n");
    writeFileSync(join(root, "registry.csv"), registry);
    const att = { createdAt: T0.toISOString(), sourceHash: sourceHash(root), suites: ["unit", "integration", "e2e"].map((name) => ({ name, passed: true, tests: 5, failures: 0 })) };
    writeFileSync(join(root, "att.json"), JSON.stringify(att));
    const cfg = loadConfig({
      EXECUTION_MODE: "LIVE_APPROVAL",
      LIVE_TRADING_ENABLED: "true",
      LIVE_TRADING_ACK: LIVE_ACK_PHRASE,
      LIVE_STRATEGY_IDS: "EXP-0100",
      REGISTRY_PATH: join(root, "registry.csv"),
      SAFETY_ATTESTATION_PATH: join(root, "att.json"),
      GROWW_ACCESS_TOKEN: "t",
      TELEGRAM_BOT_TOKEN: "b",
      TELEGRAM_ALLOWED_CHAT_ID: "1",
      TELEGRAM_ALLOWED_USER_IDS: "2",
      ...over,
    });
    return { root, cfg };
  }

  async function storeWith(workflows: number, incidents = 0) {
    const s = new MemoryStore();
    for (let i = 0; i < workflows; i++) {
      const { trade } = await import("../helpers/storeContract.js");
      await s.insertTrade(trade(`w${i}`, { state: "CLOSED" }));
      await s.appendAudit({ at: T0.toISOString(), tradeId: `w${i}`, type: "PROTECTION_CONFIRMED", payload: {} });
    }
    for (let i = 0; i < incidents; i++) await s.appendAudit({ at: T0.toISOString(), tradeId: null, type: "SAFETY_INCIDENT", payload: { incidentId: `i${i}` } });
    return s;
  }

  it("passes only when every condition holds", async () => {
    const { root, cfg } = setup();
    const r = await checkLiveGate(cfg, await storeWith(20), { root, now: T0 });
    expect(r).toEqual({ ok: true, failures: [] });
  });

  it.each([
    ["kill switch", { KILL_SWITCH: "true" }, /KILL_SWITCH/],
    ["flag off", { LIVE_TRADING_ENABLED: "false" }, /LIVE_TRADING_ENABLED/],
    ["wrong ack", { LIVE_TRADING_ACK: "yes" }, /ACK/],
    ["unaccepted strategy", { LIVE_STRATEGY_IDS: "EXP-0001" }, /not ACCEPTED/],
    ["no telegram allow-list", { TELEGRAM_ALLOWED_USER_IDS: "" }, /Telegram/],
  ])("fails closed: %s", async (_n, over, re) => {
    const { root, cfg } = setup(over as Record<string, string>);
    const r = await checkLiveGate(cfg, await storeWith(20), { root, now: T0 });
    expect(r.ok).toBe(false);
    expect(r.failures.join("\n")).toMatch(re);
  });

  it("fails without enough paper workflows or with open incidents", async () => {
    const { root, cfg } = setup();
    expect((await checkLiveGate(cfg, await storeWith(19), { root, now: T0 })).failures.join()).toMatch(/paper workflows/);
    expect((await checkLiveGate(cfg, await storeWith(20, 1), { root, now: T0 })).failures.join()).toMatch(/incidents/);
  });

  it("fails when code changed after the attestation, or the attestation is old", async () => {
    const { root, cfg } = setup();
    writeFileSync(join(root, "src", "a.ts"), "export const a = 2;\n");
    expect((await checkLiveGate(cfg, await storeWith(20), { root, now: T0 })).failures.join()).toMatch(/different code/);
    const later = new Date(T0.getTime() + 8 * 86_400_000);
    expect((await checkLiveGate(cfg, await storeWith(20), { root, now: later })).failures.join()).toMatch(/days old/);
  });
});

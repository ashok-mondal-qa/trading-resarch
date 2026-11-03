import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import type { Store } from "../store/Store.js";
import type { AppConfig } from "./config.js";

/**
 * The hard gate in front of LIVE_APPROVAL. Every check must pass or the process refuses to build a
 * live broker. Nothing here can be bypassed by a single flag:
 *
 *  1. KILL_SWITCH is off.
 *  2. LIVE_TRADING_ENABLED=true AND LIVE_TRADING_ACK equals LIVE_ACK_PHRASE exactly.
 *  3. Every id in LIVE_STRATEGY_IDS has status ACCEPTED in experiments/registry.csv
 *     (none does as of 2026-11-03: EXP-0006..0066 were all rejected after charges).
 *  4. A safety attestation (npm run safety:attest) exists, every suite passed, it is recent, and its
 *     source hash equals the hash of the code that is about to run.
 *  5. The store holds at least LIVE_MIN_PAPER_WORKFLOWS (floor 20) complete paper workflows and zero
 *     unresolved safety incidents.
 *  6. Groww credentials and a Telegram bot with an allow-listed chat and user are configured.
 */
export const LIVE_ACK_PHRASE = "I accept real-money risk and have reviewed the paper results";

export interface GateResult {
  ok: boolean;
  failures: string[];
}

export interface Attestation {
  createdAt: string;
  sourceHash: string;
  suites: { name: string; passed: boolean; tests: number; failures: number }[];
}

export function parseCsv(text: string): Record<string, string>[] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i]!;
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else inQuotes = false;
      } else field += c;
    } else if (c === '"') inQuotes = true;
    else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      field = "";
      if (row.some((f) => f !== "")) rows.push(row);
      row = [];
    } else field += c;
  }
  if (field !== "" || row.length) {
    row.push(field);
    if (row.some((f) => f !== "")) rows.push(row);
  }
  const [header, ...body] = rows;
  if (!header) return [];
  return body.map((r) => Object.fromEntries(header.map((h, i) => [h.trim(), (r[i] ?? "").trim()])));
}

export function acceptedStrategies(registryCsv: string): Set<string> {
  const out = new Set<string>();
  for (const r of parseCsv(registryCsv)) {
    if (r.status === "ACCEPTED" && r.experiment_id) out.add(r.experiment_id);
  }
  return out;
}

function walk(dir: string, acc: string[]): void {
  for (const name of readdirSync(dir).sort()) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, acc);
    else acc.push(p);
  }
}

/** sha256 over the engine's source and migrations, so an attestation is tied to exact code. */
export function sourceHash(root: string): string {
  const files: string[] = [];
  for (const d of ["src", "db"]) {
    const p = join(root, d);
    if (existsSync(p)) walk(p, files);
  }
  const h = createHash("sha256");
  for (const f of files) {
    h.update(relative(root, f).replaceAll("\\", "/"));
    h.update("\0");
    h.update(readFileSync(f));
    h.update("\0");
  }
  return h.digest("hex");
}

export async function checkLiveGate(
  cfg: AppConfig,
  store: Store,
  opts: { root: string; now: Date; readFile?: (p: string) => string | null },
): Promise<GateResult> {
  const read = opts.readFile ?? ((p: string) => (existsSync(p) ? readFileSync(p, "utf8") : null));
  const failures: string[] = [];

  if (cfg.mode !== "LIVE_APPROVAL") failures.push("EXECUTION_MODE is not LIVE_APPROVAL");
  if (cfg.killSwitch) failures.push("KILL_SWITCH is on");
  if (!cfg.live.liveTradingEnabled) failures.push("LIVE_TRADING_ENABLED is not true");
  if (cfg.live.liveAck !== LIVE_ACK_PHRASE) failures.push("LIVE_TRADING_ACK does not match the required phrase");

  if (cfg.live.liveStrategyIds.length === 0) failures.push("LIVE_STRATEGY_IDS is empty");
  const registry = read(cfg.live.registryPath);
  if (registry === null) failures.push(`strategy registry not found at ${cfg.live.registryPath}`);
  else {
    const accepted = acceptedStrategies(registry);
    for (const id of cfg.live.liveStrategyIds) {
      if (!accepted.has(id)) failures.push(`strategy ${id} is not ACCEPTED in the registry`);
    }
  }

  const attRaw = read(cfg.live.attestationPath);
  if (attRaw === null) failures.push("safety attestation missing: run `npm run safety:attest`");
  else {
    try {
      const att = JSON.parse(attRaw) as Attestation;
      const ageDays = (opts.now.getTime() - new Date(att.createdAt).getTime()) / 86_400_000;
      if (!(ageDays >= 0 && ageDays <= cfg.live.attestationMaxAgeDays)) failures.push(`safety attestation is ${ageDays.toFixed(1)} days old`);
      const needed = ["unit", "integration", "e2e"];
      for (const n of needed) {
        const s = att.suites.find((x) => x.name === n);
        if (!s || !s.passed || s.failures > 0 || s.tests === 0) failures.push(`safety suite ${n} did not pass`);
      }
      if (att.sourceHash !== sourceHash(opts.root)) failures.push("safety attestation was made for different code");
    } catch {
      failures.push("safety attestation is not valid JSON");
    }
  }

  const track = await store.paperTrackRecord();
  if (track.completedWorkflows < cfg.live.minPaperWorkflows) {
    failures.push(`only ${track.completedWorkflows} complete paper workflows, need ${cfg.live.minPaperWorkflows}`);
  }
  if (track.safetyIncidents > 0) failures.push(`${track.safetyIncidents} unresolved safety incidents in paper/live history`);

  const g = cfg.groww;
  if (!g.accessToken && !(g.apiKey && (g.apiSecret || g.totpSeed))) failures.push("Groww credentials not configured");
  const t = cfg.telegram;
  if (!t.botToken || t.allowedChatId === undefined || t.allowedUserIds.length === 0) {
    failures.push("Telegram bot token, allowed chat id and allowed user ids are required");
  }

  return { ok: failures.length === 0, failures };
}

export class LiveGateClosed extends Error {
  constructor(readonly failures: string[]) {
    super(`LIVE_APPROVAL refused:\n - ${failures.join("\n - ")}`);
    this.name = "LiveGateClosed";
  }
}

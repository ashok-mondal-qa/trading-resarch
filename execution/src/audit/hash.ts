import { createHash } from "node:crypto";
import { redact } from "../util/secret.js";

/** Deterministic JSON: object keys sorted at every level. */
export function canonicalJson(v: unknown): string {
  if (v === null || typeof v !== "object") return JSON.stringify(v ?? null);
  if (Array.isArray(v)) return `[${v.map(canonicalJson).join(",")}]`;
  const o = v as Record<string, unknown>;
  return `{${Object.keys(o)
    .filter((k) => o[k] !== undefined)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${canonicalJson(o[k])}`)
    .join(",")}}`;
}

export function sha256(s: string): string {
  return createHash("sha256").update(s).digest("hex");
}

export const GENESIS_HASH = "0".repeat(64);

export function auditHash(prevHash: string, at: string, tradeId: string | null, type: string, payload: unknown): string {
  return sha256(`${prevHash}|${at}|${tradeId ?? ""}|${type}|${canonicalJson(payload)}`);
}

/** Payloads are redacted before they are hashed and stored, so secrets never reach the audit trail. */
export function sanitizePayload(payload: Record<string, unknown>): Record<string, unknown> {
  return JSON.parse(JSON.stringify(redact(payload))) as Record<string, unknown>;
}

export interface ChainCheck {
  ok: boolean;
  brokenAtSeq?: number;
}

export function verifyChain(events: { seq: number; at: string; tradeId: string | null; type: string; payload: unknown; prevHash: string; hash: string }[]): ChainCheck {
  let prev = GENESIS_HASH;
  for (const e of [...events].sort((a, b) => a.seq - b.seq)) {
    if (e.prevHash !== prev || auditHash(prev, e.at, e.tradeId, e.type, e.payload) !== e.hash) return { ok: false, brokenAtSeq: e.seq };
    prev = e.hash;
  }
  return { ok: true };
}

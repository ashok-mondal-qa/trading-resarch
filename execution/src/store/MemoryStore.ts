import { GENESIS_HASH, auditHash, sanitizePayload } from "../audit/hash.js";
import type { ExecutionMode, TradeRecord } from "../domain/types.js";
import { isTerminal } from "../domain/stateMachine.js";
import { ConcurrencyError, type ApprovalRecord, type AuditEvent, type PaperTrackRecord, type Store } from "./Store.js";

const clone = <T>(v: T): T => structuredClone(v);

/** In-process store for tests and dry runs. Same semantics as PostgresStore, not durable. */
export class MemoryStore implements Store {
  private slots = new Map<string, string>();
  private trades = new Map<string, TradeRecord>();
  private approvals = new Map<string, ApprovalRecord>();
  private audit: AuditEvent[] = [];
  private kv = new Map<string, string>();

  async claimDailySlot(mode: ExecutionMode, tradingDay: string, tradeId: string): Promise<boolean> {
    const k = `${mode}|${tradingDay}`;
    if (this.slots.has(k)) return false;
    this.slots.set(k, tradeId);
    return true;
  }
  async dailySlotHolder(mode: ExecutionMode, tradingDay: string): Promise<string | null> {
    return this.slots.get(`${mode}|${tradingDay}`) ?? null;
  }

  async insertTrade(t: TradeRecord): Promise<void> {
    if (this.trades.has(t.tradeId)) throw new ConcurrencyError(`trade ${t.tradeId} exists`);
    this.trades.set(t.tradeId, clone(t));
  }
  async saveTrade(t: TradeRecord): Promise<void> {
    const cur = this.trades.get(t.tradeId);
    if (!cur || cur.version !== t.version - 1) throw new ConcurrencyError(`trade ${t.tradeId} version conflict`);
    this.trades.set(t.tradeId, clone(t));
  }
  async getTrade(tradeId: string): Promise<TradeRecord | null> {
    const t = this.trades.get(tradeId);
    return t ? clone(t) : null;
  }
  async listOpenTrades(mode: ExecutionMode): Promise<TradeRecord[]> {
    return [...this.trades.values()].filter((t) => t.mode === mode && !isTerminal(t.state)).map(clone);
  }

  async insertApproval(a: ApprovalRecord): Promise<void> {
    if (this.approvals.has(a.approvalId)) throw new ConcurrencyError("approval exists");
    this.approvals.set(a.approvalId, clone(a));
  }
  async getApproval(id: string): Promise<ApprovalRecord | null> {
    const a = this.approvals.get(id);
    return a ? clone(a) : null;
  }
  async decideApproval(id: string, to: "APPROVED" | "DENIED" | "EXPIRED", decidedBy: string | undefined, at: string): Promise<ApprovalRecord | null> {
    const a = this.approvals.get(id);
    if (!a || a.status !== "PENDING") return null;
    const next: ApprovalRecord = { ...a, status: to, decidedAt: at, decidedBy };
    this.approvals.set(id, next);
    return clone(next);
  }
  async setApprovalMessageId(id: string, messageId: number): Promise<void> {
    const a = this.approvals.get(id);
    if (a) a.telegramMessageId = messageId;
  }

  async appendAudit(e: Omit<AuditEvent, "seq" | "prevHash" | "hash">): Promise<AuditEvent> {
    const prevHash = this.audit.at(-1)?.hash ?? GENESIS_HASH;
    const payload = sanitizePayload(e.payload);
    const ev: AuditEvent = { ...e, payload, seq: this.audit.length + 1, prevHash, hash: auditHash(prevHash, e.at, e.tradeId, e.type, payload) };
    this.audit.push(ev);
    return clone(ev);
  }
  async listAudit(tradeId?: string): Promise<AuditEvent[]> {
    return this.audit.filter((e) => tradeId === undefined || e.tradeId === tradeId).map(clone);
  }

  async getKv(key: string): Promise<string | null> {
    return this.kv.get(key) ?? null;
  }
  async setKv(key: string, value: string): Promise<void> {
    this.kv.set(key, value);
  }

  async paperTrackRecord(): Promise<PaperTrackRecord> {
    return trackRecordFrom([...this.trades.values()], this.audit);
  }

  /** Test helper: lets a test tamper with the audit trail to prove the chain check catches it. */
  _auditForTest(): AuditEvent[] {
    return this.audit;
  }

  async close(): Promise<void> {}
}

/**
 * A complete paper workflow: a PAPER trade that went through approval, entry, confirmed protection and closed.
 * Safety incidents: audit events of type SAFETY_INCIDENT not later marked SAFETY_INCIDENT_RESOLVED.
 */
export function trackRecordFrom(trades: TradeRecord[], audit: AuditEvent[]): PaperTrackRecord {
  const protectedIds = new Set(audit.filter((e) => e.type === "PROTECTION_CONFIRMED" && e.tradeId).map((e) => e.tradeId as string));
  const completedWorkflows = trades.filter((t) => t.mode === "PAPER" && t.state === "CLOSED" && protectedIds.has(t.tradeId)).length;
  const open = new Set<string>();
  for (const e of audit) {
    const id = String(e.payload.incidentId ?? "");
    if (e.type === "SAFETY_INCIDENT") open.add(id);
    if (e.type === "SAFETY_INCIDENT_RESOLVED") open.delete(id);
  }
  return { completedWorkflows, safetyIncidents: open.size };
}

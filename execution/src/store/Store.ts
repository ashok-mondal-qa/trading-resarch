import type { ExecutionMode, TradeRecord } from "../domain/types.js";

export type ApprovalStatus = "PENDING" | "APPROVED" | "DENIED" | "EXPIRED";

export type ApprovalKind = "ENTRY" | "EXIT";

export interface ApprovalRecord {
  approvalId: string;
  tradeId: string;
  /** ENTRY: open the approved trade. EXIT: flatten an open position (e.g. protection failed, square-off). */
  kind: ApprovalKind;
  /** sha256 of the canonical order intent the human saw. Any change to the intent voids the approval. */
  intentHash: string;
  /** sha256 of the one-time nonce embedded in the Telegram button; the nonce itself is never stored. */
  nonceHash: string;
  status: ApprovalStatus;
  expiresAt: string;
  createdAt: string;
  decidedAt?: string;
  decidedBy?: string; // Telegram user id
  telegramMessageId?: number;
}

export interface AuditEvent {
  seq: number;
  at: string;
  tradeId: string | null;
  type: string;
  payload: Record<string, unknown>;
  prevHash: string;
  hash: string;
}

export interface PaperTrackRecord {
  completedWorkflows: number;
  safetyIncidents: number;
}

/**
 * Persistence port. MemoryStore (tests, dry runs) and PostgresStore (deployment) implement it.
 * Every method that guards money (claimDailySlot, decideApproval, saveTrade) must be atomic.
 */
export interface Store {
  /**
   * Claims the one-trade-per-day slot. Returns false when another trade already holds it
   * (in this mode). Implemented as a primary key on (mode, trading_day).
   */
  claimDailySlot(mode: ExecutionMode, tradingDay: string, tradeId: string): Promise<boolean>;
  dailySlotHolder(mode: ExecutionMode, tradingDay: string): Promise<string | null>;

  insertTrade(t: TradeRecord): Promise<void>;
  /** Optimistic concurrency: fails unless the stored version equals t.version - 1. */
  saveTrade(t: TradeRecord): Promise<void>;
  getTrade(tradeId: string): Promise<TradeRecord | null>;
  listOpenTrades(mode: ExecutionMode): Promise<TradeRecord[]>;

  insertApproval(a: ApprovalRecord): Promise<void>;
  getApproval(approvalId: string): Promise<ApprovalRecord | null>;
  /**
   * Atomically moves a PENDING approval to APPROVED/DENIED/EXPIRED. Returns the updated record,
   * or null if it was not PENDING any more (already used, expired or decided): single use.
   */
  decideApproval(approvalId: string, to: Exclude<ApprovalStatus, "PENDING">, decidedBy: string | undefined, at: string): Promise<ApprovalRecord | null>;
  setApprovalMessageId(approvalId: string, messageId: number): Promise<void>;

  appendAudit(e: Omit<AuditEvent, "seq" | "prevHash" | "hash">): Promise<AuditEvent>;
  listAudit(tradeId?: string): Promise<AuditEvent[]>;

  getKv(key: string): Promise<string | null>;
  setKv(key: string, value: string): Promise<void>;

  paperTrackRecord(): Promise<PaperTrackRecord>;

  close(): Promise<void>;
}

export class ConcurrencyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConcurrencyError";
  }
}

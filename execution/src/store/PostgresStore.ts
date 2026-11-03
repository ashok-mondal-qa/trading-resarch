import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import pg from "pg";
import { GENESIS_HASH, auditHash, sanitizePayload } from "../audit/hash.js";
import type { ExecutionMode, TradeRecord } from "../domain/types.js";
import { trackRecordFrom } from "./MemoryStore.js";
import { ConcurrencyError, type ApprovalRecord, type ApprovalStatus, type AuditEvent, type PaperTrackRecord, type Store } from "./Store.js";

const TERMINAL_STATES = ["RISK_REJECTED", "APPROVAL_DENIED", "APPROVAL_EXPIRED", "ENTRY_REJECTED", "ENTRY_CANCELLED", "CLOSED", "HALTED"];
const AUDIT_LOCK_KEY = 7_300_300; // advisory lock serialising the hash chain

export async function migrate(pool: pg.Pool, dir: string): Promise<string[]> {
  const client = await pool.connect();
  const applied: string[] = [];
  try {
    await client.query("SELECT pg_advisory_lock($1)", [AUDIT_LOCK_KEY + 1]);
    await client.query("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())");
    const done = new Set((await client.query<{ version: string }>("SELECT version FROM schema_migrations")).rows.map((r) => r.version));
    for (const f of readdirSync(dir).filter((x) => x.endsWith(".sql")).sort()) {
      if (done.has(f)) continue;
      await client.query("BEGIN");
      try {
        await client.query(readFileSync(join(dir, f), "utf8"));
        await client.query("INSERT INTO schema_migrations (version) VALUES ($1)", [f]);
        await client.query("COMMIT");
        applied.push(f);
      } catch (e) {
        await client.query("ROLLBACK");
        throw e;
      }
    }
  } finally {
    await client.query("SELECT pg_advisory_unlock($1)", [AUDIT_LOCK_KEY + 1]).catch(() => undefined);
    client.release();
  }
  return applied;
}

interface ApprovalRow {
  approval_id: string;
  trade_id: string;
  kind: ApprovalRecord["kind"];
  intent_hash: string;
  nonce_hash: string;
  status: ApprovalStatus;
  expires_at: Date;
  created_at: Date;
  decided_at: Date | null;
  decided_by: string | null;
  telegram_message_id: string | null;
}

function toApproval(r: ApprovalRow): ApprovalRecord {
  return {
    approvalId: r.approval_id,
    tradeId: r.trade_id,
    kind: r.kind,
    intentHash: r.intent_hash,
    nonceHash: r.nonce_hash,
    status: r.status,
    expiresAt: r.expires_at.toISOString(),
    createdAt: r.created_at.toISOString(),
    decidedAt: r.decided_at?.toISOString(),
    decidedBy: r.decided_by ?? undefined,
    telegramMessageId: r.telegram_message_id === null ? undefined : Number(r.telegram_message_id),
  };
}

interface AuditRow {
  seq: string;
  at: string;
  trade_id: string | null;
  type: string;
  payload: Record<string, unknown>;
  prev_hash: string;
  hash: string;
}

function toAudit(r: AuditRow): AuditEvent {
  return { seq: Number(r.seq), at: r.at, tradeId: r.trade_id, type: r.type, payload: r.payload, prevHash: r.prev_hash, hash: r.hash };
}

export class PostgresStore implements Store {
  constructor(private readonly pool: pg.Pool) {}

  /** The password can come separately (DATABASE_PASSWORD / DATABASE_PASSWORD_FILE) so the URL holds no secret. */
  static connect(url: string, password?: { reveal(): string }): PostgresStore {
    return new PostgresStore(new pg.Pool({ connectionString: url, max: 5, ...(password ? { password: password.reveal() } : {}) }));
  }

  migrate(dir: string): Promise<string[]> {
    return migrate(this.pool, dir);
  }

  async claimDailySlot(mode: ExecutionMode, tradingDay: string, tradeId: string): Promise<boolean> {
    const r = await this.pool.query("INSERT INTO daily_slots (mode, trading_day, trade_id) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING", [mode, tradingDay, tradeId]);
    return r.rowCount === 1;
  }
  async dailySlotHolder(mode: ExecutionMode, tradingDay: string): Promise<string | null> {
    const r = await this.pool.query<{ trade_id: string }>("SELECT trade_id FROM daily_slots WHERE mode = $1 AND trading_day = $2", [mode, tradingDay]);
    return r.rows[0]?.trade_id ?? null;
  }

  async insertTrade(t: TradeRecord): Promise<void> {
    await this.pool.query("INSERT INTO trades (trade_id, mode, trading_day, state, version, record) VALUES ($1, $2, $3, $4, $5, $6)", [
      t.tradeId,
      t.mode,
      t.tradingDay,
      t.state,
      t.version,
      JSON.stringify(t),
    ]);
  }
  async saveTrade(t: TradeRecord): Promise<void> {
    const r = await this.pool.query(
      "UPDATE trades SET state = $2, version = $3, record = $4, updated_at = now() WHERE trade_id = $1 AND version = $3 - 1",
      [t.tradeId, t.state, t.version, JSON.stringify(t)],
    );
    if (r.rowCount !== 1) throw new ConcurrencyError(`trade ${t.tradeId} version conflict`);
  }
  async getTrade(tradeId: string): Promise<TradeRecord | null> {
    const r = await this.pool.query<{ record: TradeRecord }>("SELECT record FROM trades WHERE trade_id = $1", [tradeId]);
    return r.rows[0]?.record ?? null;
  }
  async listOpenTrades(mode: ExecutionMode): Promise<TradeRecord[]> {
    const r = await this.pool.query<{ record: TradeRecord }>("SELECT record FROM trades WHERE mode = $1 AND NOT (state = ANY($2)) ORDER BY created_at", [mode, TERMINAL_STATES]);
    return r.rows.map((x) => x.record);
  }

  async insertApproval(a: ApprovalRecord): Promise<void> {
    await this.pool.query(
      "INSERT INTO approvals (approval_id, trade_id, kind, intent_hash, nonce_hash, status, expires_at, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
      [a.approvalId, a.tradeId, a.kind, a.intentHash, a.nonceHash, a.status, a.expiresAt, a.createdAt],
    );
  }
  async getApproval(id: string): Promise<ApprovalRecord | null> {
    const r = await this.pool.query<ApprovalRow>("SELECT * FROM approvals WHERE approval_id = $1", [id]);
    return r.rows[0] ? toApproval(r.rows[0]) : null;
  }
  async decideApproval(id: string, to: Exclude<ApprovalStatus, "PENDING">, decidedBy: string | undefined, at: string): Promise<ApprovalRecord | null> {
    const r = await this.pool.query<ApprovalRow>(
      "UPDATE approvals SET status = $2, decided_by = $3, decided_at = $4 WHERE approval_id = $1 AND status = 'PENDING' RETURNING *",
      [id, to, decidedBy ?? null, at],
    );
    return r.rows[0] ? toApproval(r.rows[0]) : null;
  }
  async setApprovalMessageId(id: string, messageId: number): Promise<void> {
    await this.pool.query("UPDATE approvals SET telegram_message_id = $2 WHERE approval_id = $1", [id, messageId]);
  }

  async appendAudit(e: Omit<AuditEvent, "seq" | "prevHash" | "hash">): Promise<AuditEvent> {
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("SELECT pg_advisory_xact_lock($1)", [AUDIT_LOCK_KEY]);
      const last = await client.query<{ hash: string }>("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1");
      const prevHash = last.rows[0]?.hash ?? GENESIS_HASH;
      const payload = sanitizePayload(e.payload);
      const hash = auditHash(prevHash, e.at, e.tradeId, e.type, payload);
      const r = await client.query<AuditRow>(
        "INSERT INTO audit_events (at, trade_id, type, payload, prev_hash, hash) VALUES ($1, $2, $3, $4, $5, $6) RETURNING *",
        [e.at, e.tradeId, e.type, JSON.stringify(payload), prevHash, hash],
      );
      await client.query("COMMIT");
      return toAudit(r.rows[0]!);
    } catch (err) {
      await client.query("ROLLBACK").catch(() => undefined);
      throw err;
    } finally {
      client.release();
    }
  }
  async listAudit(tradeId?: string): Promise<AuditEvent[]> {
    const r =
      tradeId === undefined
        ? await this.pool.query<AuditRow>("SELECT * FROM audit_events ORDER BY seq")
        : await this.pool.query<AuditRow>("SELECT * FROM audit_events WHERE trade_id = $1 ORDER BY seq", [tradeId]);
    return r.rows.map(toAudit);
  }

  async getKv(key: string): Promise<string | null> {
    const r = await this.pool.query<{ value: string }>("SELECT value FROM kv WHERE key = $1", [key]);
    return r.rows[0]?.value ?? null;
  }
  async setKv(key: string, value: string): Promise<void> {
    await this.pool.query("INSERT INTO kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()", [key, value]);
  }

  async paperTrackRecord(): Promise<PaperTrackRecord> {
    const trades = (await this.pool.query<{ record: TradeRecord }>("SELECT record FROM trades WHERE mode = 'PAPER' AND state = 'CLOSED'")).rows.map((r) => r.record);
    const audit = (
      await this.pool.query<AuditRow>("SELECT * FROM audit_events WHERE type IN ('PROTECTION_CONFIRMED', 'SAFETY_INCIDENT', 'SAFETY_INCIDENT_RESOLVED') ORDER BY seq")
    ).rows.map(toAudit);
    return trackRecordFrom(trades, audit);
  }

  async close(): Promise<void> {
    await this.pool.end();
  }
}

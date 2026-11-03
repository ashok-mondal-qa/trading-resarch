import { randomUUID } from "node:crypto";
import { assertTransition } from "../domain/stateMachine.js";
import type { TradeRecord, TradeState } from "../domain/types.js";
import type { Notifier } from "../approval/ports.js";
import type { Store } from "../store/Store.js";
import type { Clock } from "../util/clock.js";

export const HALT_KEY = "engine.halted";

/** Persists state changes with optimistic concurrency and writes an audit event for each one. */
export class TradeOps {
  constructor(
    readonly store: Store,
    readonly clock: Clock,
    readonly notifier: Notifier,
  ) {}

  now(): string {
    return this.clock.now().toISOString();
  }

  async audit(tradeId: string | null, type: string, payload: Record<string, unknown> = {}): Promise<void> {
    await this.store.appendAudit({ at: this.now(), tradeId, type, payload });
  }

  /** Saves field changes without a state change. */
  async patch(t: TradeRecord, changes: Partial<TradeRecord>, auditType?: string, payload: Record<string, unknown> = {}): Promise<TradeRecord> {
    const next: TradeRecord = { ...t, ...changes, version: t.version + 1, updatedAt: this.now() };
    await this.store.saveTrade(next);
    if (auditType) await this.audit(t.tradeId, auditType, payload);
    return next;
  }

  async transition(t: TradeRecord, to: TradeState, changes: Partial<TradeRecord> = {}, payload: Record<string, unknown> = {}): Promise<TradeRecord> {
    if (t.state === to) return this.patch(t, changes);
    assertTransition(t.state, to);
    const next: TradeRecord = { ...t, ...changes, state: to, version: t.version + 1, updatedAt: this.now() };
    await this.store.saveTrade(next);
    await this.audit(t.tradeId, "STATE", { from: t.state, to, ...payload });
    return next;
  }

  /** Records a safety incident and halts new entries until the owner clears it server-side. */
  async incident(tradeId: string | null, summary: string, detail: Record<string, unknown> = {}): Promise<void> {
    const incidentId = randomUUID();
    await this.audit(tradeId, "SAFETY_INCIDENT", { incidentId, summary, ...detail });
    await this.store.setKv(HALT_KEY, incidentId);
    await this.safeAlert(`⚠️ SAFETY INCIDENT: ${summary}\nNew entries are blocked until this is reviewed. Check the Groww app now.`);
  }

  /** Alerts must never break the money path: a Telegram outage is logged, not thrown. */
  async safeAlert(text: string): Promise<void> {
    try {
      await this.notifier.alert(text);
    } catch (e) {
      await this.audit(null, "ALERT_FAILED", { error: (e as Error).message, text: text.slice(0, 200) }).catch(() => undefined);
    }
  }
}

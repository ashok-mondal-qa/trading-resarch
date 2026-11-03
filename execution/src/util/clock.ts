/** Time source, injectable so tests can control market hours. All trading-day logic uses IST. */
export interface Clock {
  now(): Date;
}

export const systemClock: Clock = { now: () => new Date() };

export class FakeClock implements Clock {
  constructor(private t: Date) {}
  now(): Date {
    return new Date(this.t.getTime());
  }
  set(t: Date | string): void {
    this.t = typeof t === "string" ? new Date(t) : t;
  }
  advance(ms: number): void {
    this.t = new Date(this.t.getTime() + ms);
  }
}

const IST_OFFSET_MIN = 330;

/** YYYY-MM-DD in Asia/Kolkata. */
export function istDay(d: Date): string {
  const ist = new Date(d.getTime() + IST_OFFSET_MIN * 60_000);
  return ist.toISOString().slice(0, 10);
}

/** Minutes since IST midnight. */
export function istMinutes(d: Date): number {
  const ist = new Date(d.getTime() + IST_OFFSET_MIN * 60_000);
  return ist.getUTCHours() * 60 + ist.getUTCMinutes();
}

/** "HH:MM" -> minutes. */
export function hhmm(s: string): number {
  const m = /^(\d{2}):(\d{2})$/.exec(s);
  if (!m) throw new Error(`Bad time ${s}, expected HH:MM`);
  return Number(m[1]) * 60 + Number(m[2]);
}

/** Saturday/Sunday in IST. Exchange holidays come from config (NSE_HOLIDAYS). */
export function isIstWeekend(d: Date): boolean {
  const ist = new Date(d.getTime() + IST_OFFSET_MIN * 60_000);
  const wd = ist.getUTCDay();
  return wd === 0 || wd === 6;
}

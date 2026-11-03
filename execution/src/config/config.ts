import type { ExecutionMode } from "../domain/types.js";
import { hhmm } from "../util/clock.js";
import { readSecret, type Secret } from "../util/secret.js";

/**
 * Hard ceilings from the AI Trading Desk India brief. Config may tighten these, never loosen them:
 * loadConfig() throws if a value is outside the ceiling.
 */
export const HARD_LIMITS = Object.freeze({
  maxPlannedRiskInr: 300,
  minRewardRisk: 2,
  maxTradesPerDay: 1,
  minPaperWorkflowsForLive: 20,
  maxApprovalTtlSec: 300,
});

export interface RiskConfig {
  maxPlannedRiskInr: number;
  minRewardRisk: number;
  /** Notional cap = account cash. Keeps MIS leverage unused. */
  maxNotionalInr: number;
  maxQuoteAgeSec: number;
  entryWindowStart: string; // HH:MM IST
  entryWindowEnd: string;
  squareOffTime: string; // MIS positions: operator is asked to exit by this time
  allowDerivatives: boolean;
  allowShort: boolean;
  maxEntryDeviationPct: number;
  slippageBpsEntry: number;
  slippageBpsStop: number;
  slippageMinTicks: number;
  /** Extra % on top of estimated charges because rates are unverified. */
  chargesSafetyBufferPct: number;
  holidays: string[]; // YYYY-MM-DD
}

export interface GrowwConfig {
  baseUrl: string;
  apiKey?: Secret;
  apiSecret?: Secret;
  totpSeed?: Secret;
  accessToken?: Secret;
  requestTimeoutMs: number;
}

export interface TelegramConfig {
  apiBase: string;
  botToken?: Secret;
  allowedChatId?: number;
  allowedUserIds: number[];
  pollTimeoutSec: number;
}

export interface LiveGateConfig {
  liveTradingEnabled: boolean;
  liveAck: string;
  liveStrategyIds: string[];
  registryPath: string;
  attestationPath: string;
  attestationMaxAgeDays: number;
  minPaperWorkflows: number;
}

export interface AppConfig {
  mode: ExecutionMode;
  killSwitch: boolean;
  databaseUrl?: string;
  approvalTtlSec: number;
  oco: { maxAttempts: number; confirmTimeoutSec: number; pollIntervalMs: number };
  reconcileIntervalMs: number;
  risk: RiskConfig;
  groww: GrowwConfig;
  telegram: TelegramConfig;
  live: LiveGateConfig;
}

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

function num(env: NodeJS.ProcessEnv, name: string, dflt: number): number {
  const raw = env[name];
  if (raw === undefined || raw === "") return dflt;
  const v = Number(raw);
  if (!Number.isFinite(v)) throw new ConfigError(`${name} must be a number, got ${JSON.stringify(raw)}`);
  return v;
}

function bool(env: NodeJS.ProcessEnv, name: string, dflt: boolean): boolean {
  const raw = env[name];
  if (raw === undefined || raw === "") return dflt;
  if (raw === "true") return true;
  if (raw === "false") return false;
  throw new ConfigError(`${name} must be "true" or "false", got ${JSON.stringify(raw)}`);
}

function list(env: NodeJS.ProcessEnv, name: string): string[] {
  return (env[name] ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const modeRaw = env.EXECUTION_MODE ?? "PAPER";
  if (modeRaw !== "PAPER" && modeRaw !== "LIVE_APPROVAL") {
    throw new ConfigError(`EXECUTION_MODE must be PAPER or LIVE_APPROVAL, got ${JSON.stringify(modeRaw)}`);
  }

  const risk: RiskConfig = {
    maxPlannedRiskInr: num(env, "MAX_PLANNED_RISK_INR", HARD_LIMITS.maxPlannedRiskInr),
    minRewardRisk: num(env, "MIN_REWARD_RISK", HARD_LIMITS.minRewardRisk),
    maxNotionalInr: num(env, "MAX_NOTIONAL_INR", 15000),
    maxQuoteAgeSec: num(env, "MAX_QUOTE_AGE_SEC", 60),
    entryWindowStart: env.ENTRY_WINDOW_START ?? "09:20",
    entryWindowEnd: env.ENTRY_WINDOW_END ?? "14:30",
    squareOffTime: env.SQUARE_OFF_TIME ?? "15:05",
    allowDerivatives: bool(env, "ALLOW_DERIVATIVES", false),
    allowShort: bool(env, "ALLOW_SHORT", false),
    maxEntryDeviationPct: num(env, "MAX_ENTRY_DEVIATION_PCT", 1.0),
    slippageBpsEntry: num(env, "SLIPPAGE_BPS_ENTRY", 5),
    slippageBpsStop: num(env, "SLIPPAGE_BPS_STOP", 10),
    slippageMinTicks: num(env, "SLIPPAGE_MIN_TICKS", 1),
    chargesSafetyBufferPct: num(env, "CHARGES_SAFETY_BUFFER_PCT", 25),
    holidays: list(env, "NSE_HOLIDAYS"),
  };

  if (risk.maxPlannedRiskInr <= 0 || risk.maxPlannedRiskInr > HARD_LIMITS.maxPlannedRiskInr) {
    throw new ConfigError(`MAX_PLANNED_RISK_INR must be in (0, ${HARD_LIMITS.maxPlannedRiskInr}]`);
  }
  if (risk.minRewardRisk < HARD_LIMITS.minRewardRisk) {
    throw new ConfigError(`MIN_REWARD_RISK must be >= ${HARD_LIMITS.minRewardRisk}`);
  }
  if (risk.maxNotionalInr <= 0) throw new ConfigError("MAX_NOTIONAL_INR must be > 0");
  if (risk.slippageBpsEntry < 0 || risk.slippageBpsStop < 0 || risk.chargesSafetyBufferPct < 0) {
    throw new ConfigError("Slippage and charge buffers cannot be negative");
  }
  for (const t of [risk.entryWindowStart, risk.entryWindowEnd, risk.squareOffTime]) hhmm(t);
  if (hhmm(risk.entryWindowStart) < hhmm("09:15") || hhmm(risk.entryWindowEnd) > hhmm("15:00")) {
    throw new ConfigError("Entry window must sit inside 09:15-15:00 IST");
  }

  const approvalTtlSec = num(env, "APPROVAL_TTL_SEC", 90);
  if (approvalTtlSec <= 0 || approvalTtlSec > HARD_LIMITS.maxApprovalTtlSec) {
    throw new ConfigError(`APPROVAL_TTL_SEC must be in (0, ${HARD_LIMITS.maxApprovalTtlSec}]`);
  }

  const allowedChat = env.TELEGRAM_ALLOWED_CHAT_ID ? Number(env.TELEGRAM_ALLOWED_CHAT_ID) : undefined;
  if (allowedChat !== undefined && !Number.isInteger(allowedChat)) throw new ConfigError("TELEGRAM_ALLOWED_CHAT_ID must be an integer");
  const allowedUsers = list(env, "TELEGRAM_ALLOWED_USER_IDS").map((s) => {
    const n = Number(s);
    if (!Number.isInteger(n)) throw new ConfigError("TELEGRAM_ALLOWED_USER_IDS must be integers");
    return n;
  });

  const minPaper = num(env, "LIVE_MIN_PAPER_WORKFLOWS", HARD_LIMITS.minPaperWorkflowsForLive);
  if (minPaper < HARD_LIMITS.minPaperWorkflowsForLive) {
    throw new ConfigError(`LIVE_MIN_PAPER_WORKFLOWS cannot be below ${HARD_LIMITS.minPaperWorkflowsForLive}`);
  }

  return {
    mode: modeRaw,
    killSwitch: bool(env, "KILL_SWITCH", false),
    databaseUrl: env.DATABASE_URL || undefined,
    approvalTtlSec,
    oco: {
      maxAttempts: Math.max(1, num(env, "OCO_MAX_ATTEMPTS", 3)),
      confirmTimeoutSec: num(env, "OCO_CONFIRM_TIMEOUT_SEC", 30),
      pollIntervalMs: num(env, "OCO_POLL_INTERVAL_MS", 2000),
    },
    reconcileIntervalMs: num(env, "RECONCILE_INTERVAL_MS", 3000),
    risk,
    groww: {
      baseUrl: env.GROWW_BASE_URL ?? "https://api.groww.in/v1",
      apiKey: readSecret(env, "GROWW_API_KEY"),
      apiSecret: readSecret(env, "GROWW_API_SECRET"),
      totpSeed: readSecret(env, "GROWW_TOTP_SEED"),
      accessToken: readSecret(env, "GROWW_ACCESS_TOKEN"),
      requestTimeoutMs: num(env, "GROWW_TIMEOUT_MS", 8000),
    },
    telegram: {
      apiBase: env.TELEGRAM_API_BASE ?? "https://api.telegram.org",
      botToken: readSecret(env, "TELEGRAM_BOT_TOKEN"),
      allowedChatId: allowedChat,
      allowedUserIds: allowedUsers,
      pollTimeoutSec: num(env, "TELEGRAM_POLL_TIMEOUT_SEC", 25),
    },
    live: {
      liveTradingEnabled: bool(env, "LIVE_TRADING_ENABLED", false),
      liveAck: env.LIVE_TRADING_ACK ?? "",
      liveStrategyIds: list(env, "LIVE_STRATEGY_IDS"),
      registryPath: env.REGISTRY_PATH ?? "../experiments/registry.csv",
      attestationPath: env.SAFETY_ATTESTATION_PATH ?? "safety-attestation.json",
      attestationMaxAgeDays: num(env, "SAFETY_ATTESTATION_MAX_AGE_DAYS", 7),
      minPaperWorkflows: minPaper,
    },
  };
}

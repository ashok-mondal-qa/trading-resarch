import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { ApprovalService } from "./approval/ApprovalService.js";
import { TelegramGateway } from "./approval/TelegramGateway.js";
import type { BrokerPort, QuoteSource } from "./broker/BrokerPort.js";
import { PaperBroker } from "./broker/paper/PaperBroker.js";
import { GrowwBroker } from "./broker/groww/GrowwBroker.js";
import { GrowwTokenManager } from "./broker/groww/auth.js";
import { GrowwHttp, type HttpFetch } from "./broker/groww/http.js";
import { loadConfig, type AppConfig } from "./config/config.js";
import { LiveGateClosed, checkLiveGate } from "./config/liveGate.js";
import { ExecutionService } from "./engine/ExecutionService.js";
import { startIntake } from "./intake.js";
import { MemoryStore } from "./store/MemoryStore.js";
import { PostgresStore } from "./store/PostgresStore.js";
import type { Store } from "./store/Store.js";
import { systemClock } from "./util/clock.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

function log(msg: string, extra: Record<string, unknown> = {}): void {
  // Structured, credential-free log line. Never pass config or secrets here.
  process.stdout.write(`${JSON.stringify({ at: new Date().toISOString(), msg, ...extra })}\n`);
}

async function openStore(cfg: AppConfig): Promise<Store> {
  if (cfg.databaseUrl) {
    const pg = PostgresStore.connect(cfg.databaseUrl, cfg.databasePassword);
    const applied = await pg.migrate(join(ROOT, "db", "migrations"));
    if (applied.length) log("migrations applied", { applied });
    return pg;
  }
  if (cfg.mode === "PAPER" && cfg.allowMemoryStore) {
    log("WARNING: in-memory store; nothing survives a restart (dry run only)");
    return new MemoryStore();
  }
  throw new Error("DATABASE_URL is required (ALLOW_MEMORY_STORE=true is accepted for PAPER dry runs only)");
}

function growwRead(cfg: AppConfig): GrowwBroker | undefined {
  const g = cfg.groww;
  if (!g.accessToken && !(g.apiKey && (g.apiSecret || g.totpSeed))) return undefined;
  const f = fetch as unknown as HttpFetch;
  const http = new GrowwHttp(g.baseUrl, new GrowwTokenManager(g, f, systemClock), f, g.requestTimeoutMs);
  return new GrowwBroker(http); // read-only: the default writer refuses every order call
}

export async function main(): Promise<void> {
  const cfg = loadConfig();
  log("starting", { mode: cfg.mode, killSwitch: cfg.killSwitch });
  if (!cfg.telegram.botToken || cfg.telegram.allowedChatId === undefined || cfg.telegram.allowedUserIds.length === 0) {
    throw new Error("Telegram is required in every mode: set TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_CHAT_ID, TELEGRAM_ALLOWED_USER_IDS");
  }
  if (!cfg.intake.token) throw new Error("INTAKE_TOKEN is required");
  const store = await openStore(cfg);

  let broker: BrokerPort;
  let quotes: QuoteSource;
  let paper: PaperBroker | undefined;
  let allowedStrategyIds: Set<string> | undefined;
  const readOnlyGroww = growwRead(cfg);

  if (cfg.mode === "LIVE_APPROVAL") {
    const gate = await checkLiveGate(cfg, store, { root: ROOT, now: systemClock.now() });
    if (!gate.ok) throw new LiveGateClosed(gate.failures);
    // The live order writer (src/broker/groww/orders.ts) is wired here once the owner authorises live-capable
    // code in the repository. Until then LIVE_APPROVAL refuses to start even with a passing gate.
    throw new LiveGateClosed(["this build contains no Groww order writer (paper-only build)"]);
  } else {
    paper = new PaperBroker(systemClock);
    broker = paper;
    quotes = paper;
  }

  const telegram = new TelegramGateway(cfg.telegram, cfg.telegram.botToken);
  const savedOffset = await store.getKv("telegram.offset");
  if (savedOffset) telegram.setOffset(Number(savedOffset));
  const approvals = new ApprovalService(store, telegram, systemClock, { ttlSec: cfg.approvalTtlSec, allowedChatId: cfg.telegram.allowedChatId, allowedUserIds: cfg.telegram.allowedUserIds });
  const svc = new ExecutionService({ cfg, store, broker, quotes, approvals, notifier: telegram, clock: systemClock, allowedStrategyIds });

  await startIntake(cfg.intake.host, cfg.intake.port, cfg.intake.token, {
    propose: (p) => svc.propose(p),
    quote: paper ? (sym, price) => paper!.tick(sym, price) : undefined,
  });
  log("intake listening", { host: cfg.intake.host, port: cfg.intake.port });
  await telegram.alert(`Execution engine started in ${cfg.mode} mode.${cfg.mode === "PAPER" ? " Simulated orders only." : ""}`).catch(() => undefined);

  let stopping = false;
  const stop = () => {
    stopping = true;
  };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);

  // Telegram long-poll loop.
  void (async () => {
    while (!stopping) {
      try {
        const { callbacks, commands } = await telegram.poll();
        for (const cb of callbacks) await svc.handleCallback(cb);
        for (const c of commands) await svc.handleCommand(c);
        await store.setKv("telegram.offset", String(telegram.getOffset()));
      } catch (e) {
        log("telegram poll error", { error: (e as Error).message });
        await new Promise((r) => setTimeout(r, 3000));
      }
    }
  })();

  // Engine loop: refresh paper prices from Groww quotes (read-only) when configured, then reconcile.
  while (!stopping) {
    try {
      if (paper && readOnlyGroww) {
        for (const t of await store.listOpenTrades(cfg.mode)) {
          const q = await readOnlyGroww.getLtp(t.proposal.instrument).catch(() => undefined);
          if (q) paper.tick(t.proposal.instrument.tradingSymbol, q.price);
        }
      }
      await svc.tick();
    } catch (e) {
      log("engine cycle error", { error: (e as Error).message });
    }
    await new Promise((r) => setTimeout(r, cfg.reconcileIntervalMs));
  }
  await store.close();
  log("stopped");
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().catch((e) => {
    log("fatal", { error: (e as Error).message });
    process.exit(1);
  });
}

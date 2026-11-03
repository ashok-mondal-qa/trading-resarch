import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { verifyChain } from "./audit/hash.js";
import { loadConfig } from "./config/config.js";
import { checkLiveGate } from "./config/liveGate.js";
import { HALT_KEY } from "./engine/TradeOps.js";
import { PostgresStore } from "./store/PostgresStore.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * Operator commands (run on the server, never via Telegram):
 *   migrate                      apply database migrations
 *   status                       open trades, halt flag, paper track record
 *   verify-audit                 recompute the audit hash chain
 *   clear-halt "<reason>"        clear the halt after reviewing an incident (records who/why in the audit trail)
 *   resolve-incident <id> "<why>"  mark one safety incident resolved
 *   gate                         print the live-gate checklist (does not start anything)
 */
async function run(argv: string[]): Promise<number> {
  const cfg = loadConfig();
  if (!cfg.databaseUrl) throw new Error("DATABASE_URL is required");
  const store = PostgresStore.connect(cfg.databaseUrl, cfg.databasePassword);
  const at = new Date().toISOString();
  try {
    const [cmd, ...args] = argv;
    switch (cmd) {
      case "migrate":
        console.log(JSON.stringify(await store.migrate(join(ROOT, "db", "migrations"))));
        return 0;
      case "status": {
        const open = await store.listOpenTrades(cfg.mode);
        console.log(JSON.stringify({ mode: cfg.mode, halted: await store.getKv(HALT_KEY), track: await store.paperTrackRecord(), open: open.map((t) => ({ id: t.tradeId, symbol: t.proposal.instrument.tradingSymbol, state: t.state, filled: t.filledQuantity, position: t.confirmedPositionQuantity, protected: t.protectedQuantity })) }, null, 2));
        return 0;
      }
      case "verify-audit": {
        const r = verifyChain(await store.listAudit());
        console.log(JSON.stringify(r));
        return r.ok ? 0 : 2;
      }
      case "clear-halt": {
        const reason = args.join(" ").trim();
        if (reason.length < 10) throw new Error('give a reason of at least 10 characters: clear-halt "reviewed incident X: ..."');
        await store.appendAudit({ at, tradeId: null, type: "HALT_CLEARED", payload: { previous: await store.getKv(HALT_KEY), reason } });
        await store.setKv(HALT_KEY, ""); // empty = not halted
        console.log("halt cleared");
        return 0;
      }
      case "resolve-incident": {
        const [incidentId, ...why] = args;
        if (!incidentId || why.join(" ").trim().length < 10) throw new Error('usage: resolve-incident <incidentId> "<what was checked and fixed>"');
        await store.appendAudit({ at, tradeId: null, type: "SAFETY_INCIDENT_RESOLVED", payload: { incidentId, reason: why.join(" ") } });
        console.log("incident resolved");
        return 0;
      }
      case "gate": {
        const r = await checkLiveGate({ ...cfg, mode: "LIVE_APPROVAL" }, store, { root: ROOT, now: new Date() });
        console.log(r.ok ? "LIVE gate: PASS" : `LIVE gate: CLOSED\n - ${r.failures.join("\n - ")}`);
        return r.ok ? 0 : 3;
      }
      default:
        console.error("commands: migrate | status | verify-audit | clear-halt <reason> | resolve-incident <id> <reason> | gate");
        return 1;
    }
  } finally {
    await store.close();
  }
}

run(process.argv.slice(2)).then(
  (code) => process.exit(code),
  (e) => {
    console.error((e as Error).message);
    process.exit(1);
  },
);

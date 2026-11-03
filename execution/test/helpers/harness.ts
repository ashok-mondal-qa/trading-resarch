import { ApprovalService } from "../../src/approval/ApprovalService.js";
import type { ApprovalButtons, ApprovalCallback, Notifier } from "../../src/approval/ports.js";
import { PaperBroker, type PaperScenario } from "../../src/broker/paper/PaperBroker.js";
import type { AppConfig } from "../../src/config/config.js";
import type { TradeProposal } from "../../src/domain/types.js";
import { ExecutionService } from "../../src/engine/ExecutionService.js";
import { MemoryStore } from "../../src/store/MemoryStore.js";
import { FakeClock } from "../../src/util/clock.js";
import { T0, proposal, testConfig } from "./fixtures.js";

export const OWNER = 7;
export const CHAT = 100;

export class FakeNotifier implements Notifier {
  alerts: string[] = [];
  approvals: { messageId: number; text: string; buttons: ApprovalButtons }[] = [];
  closed: { messageId: number; text: string }[] = [];
  answers: string[] = [];
  failAlerts = false;
  private nextId = 1;
  async alert(text: string) {
    if (this.failAlerts) throw new Error("telegram down");
    this.alerts.push(text);
  }
  async requestApproval(text: string, buttons: ApprovalButtons) {
    const messageId = this.nextId++;
    this.approvals.push({ messageId, text, buttons });
    return messageId;
  }
  async closeApproval(messageId: number, text: string) {
    this.closed.push({ messageId, text });
  }
  async answerCallback(_id: string, text: string) {
    this.answers.push(text);
  }
  all(): string {
    return [...this.alerts, ...this.approvals.map((a) => a.text), ...this.closed.map((c) => c.text)].join("\n");
  }
}

export function harness(scenario: PaperScenario = {}, env: Record<string, string> = {}) {
  const clock = new FakeClock(T0);
  const cfg: AppConfig = testConfig({ TELEGRAM_ALLOWED_CHAT_ID: String(CHAT), TELEGRAM_ALLOWED_USER_IDS: String(OWNER), ...env });
  const store = new MemoryStore();
  const broker = new PaperBroker(clock, scenario);
  const notifier = new FakeNotifier();
  const approvals = new ApprovalService(store, notifier, clock, { ttlSec: cfg.approvalTtlSec, allowedChatId: CHAT, allowedUserIds: [OWNER] });
  const svc = new ExecutionService({ cfg, store, broker, quotes: broker, approvals, notifier, clock });
  const sym = proposal().instrument.tradingSymbol;
  broker.tick(sym, 999.5); // first quote, before any order exists

  let cbSeq = 0;
  const press = async (which: "approve" | "reject", idx = -1, from = OWNER, chat = CHAT) => {
    const a = notifier.approvals.at(idx);
    if (!a) throw new Error("no approval message");
    const cb: ApprovalCallback = { callbackQueryId: `cb${++cbSeq}`, fromUserId: from, chatId: chat, data: which === "approve" ? a.buttons.approveData : a.buttons.rejectData, messageId: a.messageId };
    await svc.handleCallback(cb);
  };
  const trade = async (id: string) => (await store.getTrade(id))!;
  const run = async (n = 1) => {
    for (let i = 0; i < n; i++) await svc.tick();
  };
  const propose = (over: Partial<TradeProposal> = {}) => svc.propose(proposal({ dataTimestamp: clock.now().toISOString(), ...over }));
  return { clock, cfg, store, broker, notifier, approvals, svc, sym, press, trade, run, propose };
}

import type { TelegramConfig } from "../config/config.js";
import type { Secret } from "../util/secret.js";
import type { ApprovalButtons, ApprovalCallback, Notifier } from "./ports.js";

export type FetchLike = (url: string, init: { method: string; headers: Record<string, string>; body: string; signal?: AbortSignal }) => Promise<{
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}>;

export interface TelegramCommand {
  fromUserId: number;
  chatId: number;
  text: string;
}

export class TelegramError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TelegramError";
  }
}

interface Update {
  update_id: number;
  callback_query?: { id: string; from: { id: number }; data?: string; message?: { message_id: number; chat: { id: number } } };
  message?: { message_id: number; from?: { id: number }; chat: { id: number }; text?: string };
}

/**
 * Minimal Telegram Bot API client (sendMessage, editMessageText, answerCallbackQuery, getUpdates).
 * - Plain text only (no parse_mode), so trade fields cannot inject markup.
 * - Sends only to the allow-listed chat. The bot token is used solely to build the request URL and never
 *   appears in errors, logs or messages.
 * - Messages are composed by the engine from trade fields; credentials are never part of them.
 */
export class TelegramGateway implements Notifier {
  private offset = 0;
  private readonly chatId: number;

  constructor(
    private readonly cfg: TelegramConfig,
    private readonly token: Secret,
    private readonly fetchImpl: FetchLike = fetch as unknown as FetchLike,
  ) {
    if (cfg.allowedChatId === undefined) throw new TelegramError("TELEGRAM_ALLOWED_CHAT_ID is required");
    this.chatId = cfg.allowedChatId;
  }

  private async call<T>(method: string, body: Record<string, unknown>, timeoutMs = 15_000): Promise<T> {
    const url = `${this.cfg.apiBase}/bot${this.token.reveal()}/${method}`;
    let res;
    try {
      res = await this.fetchImpl(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (e) {
      // Never surface the underlying error: some runtimes include the URL (and so the token) in it.
      throw new TelegramError(`Telegram ${method}: network error (${(e as Error)?.name ?? "Error"})`);
    }
    let data: { ok?: boolean; result?: T; description?: string } = {};
    try {
      data = (await res.json()) as typeof data;
    } catch {
      /* fall through */
    }
    if (!res.ok || !data.ok) throw new TelegramError(`Telegram ${method}: HTTP ${res.status} ${String(data.description ?? "").slice(0, 120)}`);
    return data.result as T;
  }

  async alert(text: string): Promise<void> {
    await this.call("sendMessage", { chat_id: this.chatId, text: text.slice(0, 4000), disable_web_page_preview: true });
  }

  async requestApproval(text: string, buttons: ApprovalButtons): Promise<number> {
    const r = await this.call<{ message_id: number }>("sendMessage", {
      chat_id: this.chatId,
      text: text.slice(0, 4000),
      disable_web_page_preview: true,
      reply_markup: {
        inline_keyboard: [[
          { text: "✅ Approve entry", callback_data: buttons.approveData },
          { text: "❌ Reject", callback_data: buttons.rejectData },
        ]],
      },
    });
    return r.message_id;
  }

  async closeApproval(messageId: number, text: string): Promise<void> {
    await this.call("editMessageText", { chat_id: this.chatId, message_id: messageId, text: text.slice(0, 4000) });
  }

  async answerCallback(callbackQueryId: string, text: string): Promise<void> {
    await this.call("answerCallbackQuery", { callback_query_id: callbackQueryId, text: text.slice(0, 190) });
  }

  /**
   * One long-poll round. Returns button presses and text commands; everything else is dropped.
   * The offset is advanced so each update is handled once.
   */
  async poll(): Promise<{ callbacks: ApprovalCallback[]; commands: TelegramCommand[] }> {
    const updates = await this.call<Update[]>(
      "getUpdates",
      { offset: this.offset, timeout: this.cfg.pollTimeoutSec, allowed_updates: ["callback_query", "message"] },
      (this.cfg.pollTimeoutSec + 10) * 1000,
    );
    const callbacks: ApprovalCallback[] = [];
    const commands: TelegramCommand[] = [];
    for (const u of updates) {
      this.offset = Math.max(this.offset, u.update_id + 1);
      const cq = u.callback_query;
      if (cq?.data && cq.message) {
        callbacks.push({ callbackQueryId: cq.id, fromUserId: cq.from.id, chatId: cq.message.chat.id, data: cq.data, messageId: cq.message.message_id });
      } else if (u.message?.text && u.message.from) {
        commands.push({ fromUserId: u.message.from.id, chatId: u.message.chat.id, text: u.message.text.trim() });
      }
    }
    return { callbacks, commands };
  }

  setOffset(offset: number): void {
    this.offset = offset;
  }
  getOffset(): number {
    return this.offset;
  }
}

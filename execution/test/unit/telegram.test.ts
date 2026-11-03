import { describe, expect, it } from "vitest";
import { TelegramGateway, type FetchLike } from "../../src/approval/TelegramGateway.js";
import { loadConfig } from "../../src/config/config.js";
import { Secret } from "../../src/util/secret.js";

const TOKEN = "123456:SECRET-BOT-TOKEN";

function gateway(responder: (method: string, body: Record<string, unknown>) => unknown, opts: { throwNetwork?: boolean; status?: number } = {}) {
  const calls: { url: string; method: string; body: Record<string, unknown> }[] = [];
  const f: FetchLike = async (url, init) => {
    const method = url.split("/").pop()!;
    const body = JSON.parse(init.body) as Record<string, unknown>;
    calls.push({ url, method, body });
    if (opts.throwNetwork) throw new TypeError(`fetch failed for ${url}`);
    return { ok: (opts.status ?? 200) < 300, status: opts.status ?? 200, json: async () => ({ ok: (opts.status ?? 200) < 300, result: responder(method, body), description: "Bad Request" }) };
  };
  const cfg = loadConfig({ TELEGRAM_ALLOWED_CHAT_ID: "100", TELEGRAM_ALLOWED_USER_IDS: "7" }).telegram;
  return { gw: new TelegramGateway(cfg, new Secret(TOKEN), f), calls };
}

describe("TelegramGateway", () => {
  it("sends approval buttons as plain text to the allow-listed chat only", async () => {
    const { gw, calls } = gateway(() => ({ message_id: 55 }));
    const id = await gw.requestApproval("Approve?", { approveData: "a|x|y", rejectData: "r|x|y" });
    expect(id).toBe(55);
    const c = calls[0]!;
    expect(c.method).toBe("sendMessage");
    expect(c.body.chat_id).toBe(100);
    expect(c.body.parse_mode).toBeUndefined();
    expect(JSON.stringify(c.body)).not.toContain(TOKEN);
    expect(JSON.stringify(c.body.reply_markup)).toContain("a|x|y");
  });

  it("parses callbacks and commands and advances the offset", async () => {
    const { gw, calls } = gateway(() => [
      { update_id: 10, callback_query: { id: "q1", from: { id: 7 }, data: "a|x|y", message: { message_id: 5, chat: { id: 100 } } } },
      { update_id: 11, message: { message_id: 6, from: { id: 7 }, chat: { id: 100 }, text: " /status " } },
      { update_id: 12, edited_message: {} },
    ]);
    const r = await gw.poll();
    expect(r.callbacks).toEqual([{ callbackQueryId: "q1", fromUserId: 7, chatId: 100, data: "a|x|y", messageId: 5 }]);
    expect(r.commands).toEqual([{ fromUserId: 7, chatId: 100, text: "/status" }]);
    expect(gw.getOffset()).toBe(13);
    await gw.poll();
    expect(calls[1]!.body.offset).toBe(13);
  });

  it("never leaks the bot token in errors", async () => {
    const net = gateway(() => null, { throwNetwork: true });
    await expect(net.gw.alert("x")).rejects.toThrow(/network error/);
    await net.gw.alert("x").catch((e: Error) => expect(e.message + e.stack).not.toContain(TOKEN));
    const http = gateway(() => null, { status: 400 });
    await http.gw.alert("x").catch((e: Error) => {
      expect(e.message).toMatch(/HTTP 400/);
      expect(e.message).not.toContain(TOKEN);
    });
  });
});

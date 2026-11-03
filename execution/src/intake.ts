import { createServer, type Server } from "node:http";
import { timingSafeEqual } from "node:crypto";
import { parseProposal, ProposalError } from "./domain/parseProposal.js";
import type { TradeProposal, TradeRecord } from "./domain/types.js";
import type { Secret } from "./util/secret.js";

/**
 * Local intake for the research side: POST /proposals with a TradeProposal JSON body.
 * Binds to 127.0.0.1 (or the private Docker network) and requires `Authorization: Bearer <INTAKE_TOKEN>`.
 * A proposal is only a request: it goes through the risk engine and Telegram approval like any other.
 * PAPER only: POST /quotes {symbol, price} feeds the paper broker when no Groww quote feed is configured.
 */
export interface IntakeHandlers {
  propose(p: TradeProposal): Promise<TradeRecord>;
  quote?(symbol: string, price: number): void;
}

function bearerOk(header: string | undefined, token: Secret): boolean {
  const want = Buffer.from(`Bearer ${token.reveal()}`);
  const got = Buffer.from(header ?? "");
  return got.length === want.length && timingSafeEqual(got, want);
}

export function startIntake(host: string, port: number, token: Secret, h: IntakeHandlers): Promise<Server> {
  const server = createServer(async (req, res) => {
    const send = (status: number, body: unknown) => {
      res.writeHead(status, { "Content-Type": "application/json" });
      res.end(JSON.stringify(body));
    };
    if (req.method === "GET" && req.url === "/health") return send(200, { ok: true });
    if (!bearerOk(req.headers.authorization, token)) return send(401, { error: "unauthorized" });
    const chunks: Buffer[] = [];
    let size = 0;
    for await (const c of req) {
      size += (c as Buffer).length;
      if (size > 64 * 1024) return send(413, { error: "too large" });
      chunks.push(c as Buffer);
    }
    let body: unknown;
    try {
      body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    } catch {
      return send(400, { error: "invalid JSON" });
    }
    try {
      if (req.method === "POST" && req.url === "/proposals") {
        const t = await h.propose(parseProposal(body));
        return send(200, { tradeId: t.tradeId, state: t.state, reasons: t.risk?.reasons ?? [] });
      }
      if (req.method === "POST" && req.url === "/quotes" && h.quote) {
        const q = body as { symbol?: unknown; price?: unknown };
        if (typeof q.symbol !== "string" || typeof q.price !== "number" || !(q.price > 0)) return send(400, { error: "symbol and positive price required" });
        h.quote(q.symbol, q.price);
        return send(200, { ok: true });
      }
      return send(404, { error: "not found" });
    } catch (e) {
      return send(e instanceof ProposalError ? 400 : 500, { error: (e as Error).message });
    }
  });
  return new Promise((resolve) => server.listen(port, host, () => resolve(server)));
}

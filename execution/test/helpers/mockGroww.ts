import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";

/**
 * A local HTTP stand-in for api.groww.in/v1. Payload shapes follow docs/UNVERIFIED.md (our best reading of
 * Groww's docs); they are test fixtures, not market data. Handlers can be swapped per test to inject 401s,
 * 5xx, timeouts and FAILURE envelopes.
 */
export interface Recorded {
  method: string;
  path: string;
  query: URLSearchParams;
  headers: IncomingMessage["headers"];
  body: unknown;
}

export type Handler = (r: Recorded) => { status?: number; body?: unknown; delayMs?: number; raw?: string } | undefined;

export class MockGroww {
  server!: Server;
  base = "";
  calls: Recorded[] = [];
  handlers: Handler[] = [];

  async start(): Promise<this> {
    this.server = createServer((req, res) => void this.handle(req, res));
    await new Promise<void>((r) => this.server.listen(0, "127.0.0.1", r));
    this.base = `http://127.0.0.1:${(this.server.address() as AddressInfo).port}/v1`;
    return this;
  }

  async stop(): Promise<void> {
    this.server.closeAllConnections();
    await new Promise<void>((r) => this.server.close(() => r()));
  }

  on(h: Handler): void {
    this.handlers.unshift(h);
  }

  private async handle(req: IncomingMessage, res: ServerResponse) {
    const chunks: Buffer[] = [];
    for await (const c of req) chunks.push(c as Buffer);
    const url = new URL(req.url ?? "/", "http://x");
    const text = Buffer.concat(chunks).toString("utf8");
    const rec: Recorded = { method: req.method ?? "GET", path: url.pathname.replace(/^\/v1/, ""), query: url.searchParams, headers: req.headers, body: text ? JSON.parse(text) : undefined };
    this.calls.push(rec);
    let out: ReturnType<Handler>;
    for (const h of this.handlers) {
      out = h(rec);
      if (out) break;
    }
    out ??= { status: 404, body: { status: "FAILURE", error: { code: "404", message: "not found" } } };
    if (out.delayMs) await new Promise((r) => setTimeout(r, out!.delayMs));
    if (res.destroyed) return;
    res.writeHead(out.status ?? 200, { "Content-Type": "application/json" });
    res.end(out.raw ?? JSON.stringify(out.body ?? {}));
  }
}

export const ok = (payload: unknown) => ({ status: 200, body: { status: "SUCCESS", payload } });
export const failure = (status: number, code: string, message: string) => ({ status, body: { status: "FAILURE", error: { code, message } } });

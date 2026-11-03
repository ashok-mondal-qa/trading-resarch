import { randomUUID } from "node:crypto";
import { BrokerAuthError, BrokerError, BrokerRejectedError, BrokerUncertainError } from "../BrokerPort.js";

export type HttpFetch = (url: string, init: { method: string; headers: Record<string, string>; body?: string; signal?: AbortSignal }) => Promise<{
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}>;

export interface TokenSource {
  token(): Promise<string>;
  invalidate(): void;
}

/**
 * Thin JSON client for https://api.groww.in/v1.
 *
 * Response envelope (from the official Python SDK's _parse_response): {"status": "SUCCESS", "payload": {...}}
 * or {"status": "FAILURE", "error": {"code", "message"}}.
 *
 * Error classes, chosen so a request is never assumed to have failed when it may have succeeded:
 *  - network error, timeout, 5xx, 429, unparseable body on a WRITE -> BrokerUncertainError (look up by reference)
 *  - status FAILURE, 400, 403, 404 -> BrokerRejectedError (the broker answered no)
 *  - 401 -> token refreshed once and the request retried (a 401 was not processed); then BrokerAuthError
 * For READS every failure is a plain BrokerError: the caller treats the object's state as unknown.
 */
export class GrowwHttp {
  constructor(
    private readonly baseUrl: string,
    private readonly tokens: TokenSource,
    private readonly fetchImpl: HttpFetch,
    private readonly timeoutMs: number,
  ) {}

  async get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
    const qs = Object.entries(params)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join("&");
    return this.request<T>("GET", `${path}${qs ? `?${qs}` : ""}`, undefined, false);
  }

  async write<T>(method: "POST" | "PUT", path: string, body?: unknown): Promise<T> {
    return this.request<T>(method, path, body, true);
  }

  private async request<T>(method: string, path: string, body: unknown, isWrite: boolean, retried = false): Promise<T> {
    const token = await this.tokens.token();
    let res;
    try {
      res = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
          Accept: "application/json",
          "x-api-version": "1.0",
          "x-request-id": randomUUID(),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(this.timeoutMs),
      });
    } catch (e) {
      const msg = `Groww ${method} ${path}: no response (${(e as Error)?.name ?? "Error"})`;
      throw isWrite ? new BrokerUncertainError(msg, "NETWORK") : new BrokerError(msg, "NETWORK");
    }

    if (res.status === 401) {
      this.tokens.invalidate();
      if (!retried) return this.request<T>(method, path, body, isWrite, true);
      throw new BrokerAuthError(`Groww ${method} ${path}: authentication failed`, "401");
    }

    let data: { status?: string; payload?: unknown; error?: { code?: string; message?: string } } | undefined;
    try {
      data = (await res.json()) as typeof data;
    } catch {
      data = undefined;
    }

    if (data?.status === "FAILURE") {
      const code = String(data.error?.code ?? res.status);
      const message = String(data.error?.message ?? "request failed").slice(0, 200);
      if (res.status >= 500 || res.status === 429) throw isWrite ? new BrokerUncertainError(message, code) : new BrokerError(message, code);
      throw new BrokerRejectedError(`Groww: ${message}`, code);
    }
    if (!res.ok || data === undefined) {
      const msg = `Groww ${method} ${path}: HTTP ${res.status}`;
      if ([400, 403, 404].includes(res.status)) throw new BrokerRejectedError(msg, String(res.status));
      throw isWrite ? new BrokerUncertainError(msg, String(res.status)) : new BrokerError(msg, String(res.status));
    }
    return ((data as { payload?: unknown }).payload ?? data) as T;
  }
}

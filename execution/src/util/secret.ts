import { readFileSync } from "node:fs";

/**
 * Wraps a credential so it cannot leak through logging, JSON serialisation, audit payloads or
 * Telegram messages. The raw value is only reachable through reveal(), which is called in exactly
 * two places: the Groww token request and the Telegram Bot API URL.
 */
export class Secret {
  readonly #value: string;
  constructor(value: string) {
    if (!value) throw new Error("Secret must not be empty");
    this.#value = value;
  }
  reveal(): string {
    return this.#value;
  }
  toString(): string {
    return "[REDACTED]";
  }
  toJSON(): string {
    return "[REDACTED]";
  }
  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return "[REDACTED]";
  }
}

/** Reads NAME, or the file named by NAME_FILE (Docker / Kubernetes secrets). */
export function readSecret(env: NodeJS.ProcessEnv, name: string): Secret | undefined {
  const file = env[`${name}_FILE`];
  if (file) {
    const v = readFileSync(file, "utf8").trim();
    return v ? new Secret(v) : undefined;
  }
  const v = env[name];
  return v ? new Secret(v) : undefined;
}

const SECRET_KEY = /(token|secret|password|api[_-]?key|authorization|totp|checksum|cookie)/i;

/** Deep-copies a value replacing secret-looking keys and Secret instances. Used before audit/log/Telegram. */
export function redact(value: unknown, depth = 0): unknown {
  if (depth > 8) return "[DEPTH]";
  if (value instanceof Secret) return "[REDACTED]";
  if (Array.isArray(value)) return value.map((v) => redact(v, depth + 1));
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = SECRET_KEY.test(k) ? "[REDACTED]" : redact(v, depth + 1);
    }
    return out;
  }
  if (typeof value === "string" && /^Bearer\s+/i.test(value)) return "[REDACTED]";
  return value;
}

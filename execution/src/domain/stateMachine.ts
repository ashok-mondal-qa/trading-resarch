import type { TradeState } from "./types.js";

/**
 * Allowed trade-state transitions. Anything not listed is a bug and throws.
 * HALTED is reachable from every non-terminal state (reconciliation mismatch, kill switch).
 */
const TRANSITIONS: Record<TradeState, readonly TradeState[]> = {
  PROPOSED: ["RISK_REJECTED", "AWAITING_APPROVAL"],
  RISK_REJECTED: [],
  AWAITING_APPROVAL: ["APPROVED", "APPROVAL_DENIED", "APPROVAL_EXPIRED"],
  APPROVAL_DENIED: [],
  APPROVAL_EXPIRED: [],
  APPROVED: ["ENTRY_SUBMITTING", "RISK_REJECTED"],
  ENTRY_SUBMITTING: ["ENTRY_PENDING", "ENTRY_REJECTED", "ENTRY_UNCERTAIN"],
  ENTRY_UNCERTAIN: ["ENTRY_PENDING", "ENTRY_REJECTED", "ENTRY_CANCELLED", "POSITION_UNPROTECTED"],
  ENTRY_REJECTED: [],
  ENTRY_PENDING: ["ENTRY_CANCELLED", "ENTRY_REJECTED", "POSITION_UNPROTECTED"],
  ENTRY_CANCELLED: [],
  POSITION_UNPROTECTED: ["PROTECTION_PENDING", "PROTECTION_FAILED", "EXIT_PENDING", "CLOSED"],
  PROTECTION_PENDING: ["PROTECTED", "POSITION_UNPROTECTED", "PROTECTION_FAILED", "CLOSED"],
  // More entry fills arrive while protected: back to unprotected until the OCO quantity is raised.
  PROTECTED: ["POSITION_UNPROTECTED", "PROTECTION_PENDING", "EXIT_PENDING", "CLOSED"],
  PROTECTION_FAILED: ["PROTECTION_PENDING", "EXIT_PENDING", "CLOSED"],
  EXIT_PENDING: ["CLOSED", "POSITION_UNPROTECTED"],
  CLOSED: [],
  HALTED: [],
};

const TERMINAL: ReadonlySet<TradeState> = new Set([
  "RISK_REJECTED",
  "APPROVAL_DENIED",
  "APPROVAL_EXPIRED",
  "ENTRY_REJECTED",
  "ENTRY_CANCELLED",
  "CLOSED",
  "HALTED",
]);

/** States in which money may be at risk at the broker (an order could be live or a position open). */
const AT_BROKER: ReadonlySet<TradeState> = new Set([
  "ENTRY_SUBMITTING",
  "ENTRY_UNCERTAIN",
  "ENTRY_PENDING",
  "POSITION_UNPROTECTED",
  "PROTECTION_PENDING",
  "PROTECTED",
  "PROTECTION_FAILED",
  "EXIT_PENDING",
]);

export class IllegalTransition extends Error {
  constructor(from: TradeState, to: TradeState) {
    super(`Illegal trade transition ${from} -> ${to}`);
    this.name = "IllegalTransition";
  }
}

export function canTransition(from: TradeState, to: TradeState): boolean {
  if (to === "HALTED") return !TERMINAL.has(from);
  return TRANSITIONS[from].includes(to);
}

export function assertTransition(from: TradeState, to: TradeState): void {
  if (!canTransition(from, to)) throw new IllegalTransition(from, to);
}

export function isTerminal(s: TradeState): boolean {
  return TERMINAL.has(s);
}

export function isAtBroker(s: TradeState): boolean {
  return AT_BROKER.has(s);
}

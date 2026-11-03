/**
 * Core domain types. Everything the engine knows about a trade lives here, independent of any broker.
 *
 * Money is in INR, prices in rupees. Quantities are whole units (shares, or contracts for F&O where
 * quantity must be a multiple of the lot size).
 */

export type ExecutionMode = "PAPER" | "LIVE_APPROVAL";

export type Exchange = "NSE";
export type Segment = "CASH" | "FNO";
export type InstrumentType = "EQ" | "FUT" | "CE" | "PE";
export type Product = "MIS" | "CNC" | "NRML";
export type Side = "BUY" | "SELL";
export type Direction = "LONG" | "SHORT";
export type EntryOrderType = "LIMIT" | "SL";

export interface Instrument {
  tradingSymbol: string;
  exchange: Exchange;
  segment: Segment;
  instrumentType: InstrumentType;
  /** 1 for cash equity; the exchange lot size for F&O. */
  lotSize: number;
  tickSize: number;
  underlying?: string;
  expiry?: string; // YYYY-MM-DD
}

/**
 * What the research side (daily scan) hands to the engine. It is a request, not an order:
 * it must pass the risk engine and a one-time Telegram approval before anything is sent.
 */
export interface TradeProposal {
  proposalId: string;
  /** Strategy / experiment id, e.g. "EXP-0053". LIVE needs it ACCEPTED in experiments/registry.csv. */
  strategyId: string;
  /** IST trading day, YYYY-MM-DD. */
  tradingDay: string;
  instrument: Instrument;
  direction: Direction;
  product: Product;
  entry: { orderType: EntryOrderType; price: number; triggerPrice?: number };
  stopLoss: number;
  target: number;
  quantity: number;
  /** Last traded price the proposal was built from, and when (ISO 8601 with offset). */
  referencePrice: number;
  dataTimestamp: string;
  createdAt: string;
  notes?: string;
}

export interface ChargeBreakdown {
  brokerage: number;
  stt: number;
  exchangeTxn: number;
  sebiFee: number;
  stampDuty: number;
  gst: number;
  dpCharge: number;
  /** Extra margin added because the rates are not verified against the broker's schedule. */
  safetyBuffer: number;
  total: number;
}

export interface RiskMetrics {
  perUnitRisk: number;
  grossRiskInr: number;
  slippageInr: number;
  chargesAtStopInr: number;
  chargesAtTargetInr: number;
  /** Planned monetary risk = gross risk + slippage on both legs + round-trip charges at the stop. */
  plannedRiskInr: number;
  netRewardInr: number;
  /** netReward / plannedRisk. Must be >= minRewardRisk. */
  rewardRiskNet: number;
  notionalInr: number;
}

export interface RiskDecision {
  approved: boolean;
  reasons: string[];
  metrics: RiskMetrics | null;
  checkedAt: string;
}

/** Broker-independent order status. Fill quantity never comes from status alone. */
export type NormalizedOrderStatus =
  | "PENDING" // accepted / open / trigger pending / modification or cancel requested
  | "PARTIALLY_FILLED"
  | "FILLED"
  | "CANCELLED"
  | "REJECTED"
  | "UNKNOWN"; // unrecognised status or the order cannot be found: treat as possibly live

export interface OrderRequest {
  /** Our idempotency / correlation id, sent to the broker as order_reference_id. */
  clientRef: string;
  instrument: Instrument;
  side: Side;
  product: Product;
  orderType: "LIMIT" | "MARKET" | "SL" | "SL_M";
  quantity: number;
  price?: number;
  triggerPrice?: number;
  validity: "DAY" | "IOC";
}

export interface OrderAck {
  brokerOrderId: string;
  clientRef: string;
  /** Raw broker status at acceptance time. Acceptance is NOT a fill. */
  rawStatus: string;
}

export interface Fill {
  brokerTradeId: string;
  brokerOrderId: string;
  quantity: number;
  price: number;
  at: string;
}

export interface OrderSnapshot {
  brokerOrderId: string;
  clientRef?: string;
  status: NormalizedOrderStatus;
  rawStatus: string;
  orderedQuantity: number;
  /** As reported by the broker's order record (may lag the trade list). */
  reportedFilledQuantity: number;
  averageFillPrice?: number;
  remark?: string;
}

export interface PositionSnapshot {
  tradingSymbol: string;
  segment: Segment;
  /** Signed net quantity for the day/product: + long, − short. */
  netQuantity: number;
  averagePrice?: number;
}

export type ProtectionStatus =
  | "PENDING" // submitted, acceptance not yet confirmed
  | "ACTIVE" // broker confirms the OCO is live
  | "TRIGGERED"
  | "COMPLETED"
  | "CANCELLED"
  | "EXPIRED"
  | "FAILED"
  | "UNKNOWN";

export interface OcoRequest {
  clientRef: string;
  instrument: Instrument;
  product: Product;
  /** Quantity to protect. */
  quantity: number;
  /** Current net position in the symbol, as confirmed by the broker. */
  netPositionQuantity: number;
  /** Exit side: SELL to protect a long, BUY to protect a short. */
  exitSide: Side;
  targetPrice: number;
  stopTriggerPrice: number;
  /** Stop leg executes as market once triggered (SL_M equivalent) unless a limit is given. */
  stopLimitPrice?: number;
}

export interface OcoSnapshot {
  brokerOcoId: string;
  clientRef?: string;
  status: ProtectionStatus;
  rawStatus: string;
  quantity: number;
  remark?: string;
}

/** Lifecycle of one trade. See docs/ARCHITECTURE.md for the transition diagram. */
export type TradeState =
  | "PROPOSED"
  | "RISK_REJECTED"
  | "AWAITING_APPROVAL"
  | "APPROVAL_DENIED"
  | "APPROVAL_EXPIRED"
  | "APPROVED"
  | "ENTRY_SUBMITTING"
  | "ENTRY_UNCERTAIN" // submit outcome unknown (timeout / network); never resubmitted blindly
  | "ENTRY_REJECTED"
  | "ENTRY_PENDING"
  | "ENTRY_CANCELLED" // cancelled or expired with zero fills
  | "POSITION_UNPROTECTED" // fills confirmed, no confirmed OCO yet
  | "PROTECTION_PENDING" // OCO submitted, acceptance not yet confirmed
  | "PROTECTED" // OCO ACTIVE and covers the confirmed position quantity
  | "PROTECTION_FAILED" // OCO rejected / failed after retries: human action required
  | "EXIT_PENDING"
  | "CLOSED"
  | "HALTED"; // reconciliation mismatch or unrecoverable error: human action required

export interface TradeRecord {
  tradeId: string;
  mode: ExecutionMode;
  tradingDay: string;
  proposal: TradeProposal;
  state: TradeState;
  risk: RiskDecision | null;
  approvalId?: string;
  entryClientRef: string;
  entryOrderId?: string;
  /** Sum of broker trade-list fills for the entry order. */
  filledQuantity: number;
  averageEntryPrice?: number;
  /** Net position the broker reports for this symbol. */
  confirmedPositionQuantity: number;
  ocoClientRef?: string;
  ocoId?: string;
  protectedQuantity: number;
  ocoAttempts: number;
  /** When the current OCO request was sent; drives the confirmation timeout. */
  ocoSubmittedAt?: string;
  exitApprovalId?: string;
  exitClientRef?: string;
  exitOrderId?: string;
  exitPrice?: number;
  /** Gross P&L from fills minus estimated (unverified) charges; undefined when exit fills are unknown. */
  realisedPnlInr?: number;
  closeReason?: string;
  /** One-shot alert flags so a stuck state does not spam Telegram every cycle. */
  flags: { uncertainAlerted?: boolean; mismatchReported?: boolean; squareOffAsked?: boolean; protectionFailedAlerted?: boolean };
  lastError?: string;
  version: number;
  createdAt: string;
  updatedAt: string;
}

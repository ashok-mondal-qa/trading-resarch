import type {
  Fill,
  Instrument,
  OcoRequest,
  OcoSnapshot,
  OrderAck,
  OrderRequest,
  OrderSnapshot,
  PositionSnapshot,
  Segment,
} from "../domain/types.js";

/**
 * The only way the engine talks to a broker. Two implementations exist:
 * - PaperBroker: simulated, never leaves the process.
 * - GrowwBroker: the real Groww Trade API, constructed only after the live gate passes.
 *
 * Contract every implementation must honour:
 * 1. A resolved submit means the broker ACCEPTED the request. It never means filled.
 * 2. Fills are read from listFills() (the broker's trade list), never inferred from status.
 * 3. A transport failure (timeout, connection reset) throws BrokerUncertainError: the request may or may
 *    not have reached the broker. Callers must look it up by clientRef before trying again.
 * 4. A definite refusal (4xx business rejection) throws BrokerRejectedError.
 * 5. Methods never log or return credentials.
 */
export interface BrokerPort {
  readonly kind: "PAPER" | "GROWW";

  submitOrder(req: OrderRequest): Promise<OrderAck>;
  modifyOrder(brokerOrderId: string, segment: Segment, changes: { quantity: number; price?: number; triggerPrice?: number; orderType: OrderRequest["orderType"] }): Promise<void>;
  cancelOrder(brokerOrderId: string, segment: Segment): Promise<void>;

  getOrder(brokerOrderId: string, segment: Segment): Promise<OrderSnapshot>;
  /** Returns null when the broker has no order with this reference. */
  findOrderByClientRef(clientRef: string, segment: Segment): Promise<OrderSnapshot | null>;
  listFills(brokerOrderId: string, segment: Segment): Promise<Fill[]>;
  getPosition(tradingSymbol: string, segment: Segment): Promise<PositionSnapshot>;

  submitOco(req: OcoRequest): Promise<{ brokerOcoId: string; rawStatus: string }>;
  modifyOco(brokerOcoId: string, segment: Segment, changes: { quantity?: number; targetPrice?: number; stopTriggerPrice?: number }): Promise<void>;
  cancelOco(brokerOcoId: string, segment: Segment): Promise<void>;
  getOco(brokerOcoId: string, segment: Segment): Promise<OcoSnapshot>;
  /** Returns null when no smart order carries this reference. */
  findOcoByClientRef(clientRef: string, segment: Segment): Promise<OcoSnapshot | null>;

  /** Which OCO leg filled and at what price, when the broker can say. Undefined = unknown (check the app). */
  describeExit?(brokerOcoId: string, segment: Segment): Promise<{ price: number; quantity: number; leg: "TARGET" | "STOP" } | undefined>;
}

/** Read-only last traded price, used to re-check a setup at approval time. */
export interface QuoteSource {
  getLtp(inst: Instrument): Promise<{ price: number; at: string }>;
}

export class BrokerError extends Error {
  constructor(message: string, readonly code?: string) {
    super(message);
    this.name = "BrokerError";
  }
}

/** The broker definitely refused the request (validation, RMS, margin, market closed, ...). */
export class BrokerRejectedError extends BrokerError {
  constructor(message: string, code?: string) {
    super(message, code);
    this.name = "BrokerRejectedError";
  }
}

/** The outcome is unknown: the request may or may not have reached the broker. */
export class BrokerUncertainError extends BrokerError {
  constructor(message: string, code?: string) {
    super(message, code);
    this.name = "BrokerUncertainError";
  }
}

/** Auth failed (401/403). Never retried with the same token; the token manager must refresh. */
export class BrokerAuthError extends BrokerError {
  constructor(message: string, code?: string) {
    super(message, code);
    this.name = "BrokerAuthError";
  }
}

/** A response did not match the documented shape; treat the object's state as UNKNOWN. */
export class BrokerShapeError extends BrokerError {
  constructor(message: string) {
    super(message, "SHAPE");
    this.name = "BrokerShapeError";
  }
}

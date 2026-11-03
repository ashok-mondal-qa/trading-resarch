import type {
  Fill,
  Instrument,
  OcoRequest,
  OcoSnapshot,
  OrderAck,
  OrderRequest,
  OrderSnapshot,
  PositionSnapshot,
  ProtectionStatus,
  Segment,
} from "../../domain/types.js";
import type { Clock } from "../../util/clock.js";
import { BrokerRejectedError, BrokerUncertainError, type BrokerPort, type QuoteSource } from "../BrokerPort.js";

/**
 * Simulated broker. Nothing leaves the process. Prices come from tick() calls (a quote feed or a test).
 * Scenario knobs let tests reproduce real failure modes: rejections, timeouts after acceptance, partial
 * fills, OCO rejection, delayed OCO activation.
 */
export interface PaperScenario {
  rejectEntry?: string;
  /** The entry reaches the "exchange" but the response is lost (network timeout). */
  entryTimeoutAfterAccept?: boolean;
  /** Fill sizes for successive entry fills, e.g. [5, 7] = partial then rest. Default: all at once. */
  entryFillSizes?: number[];
  /** Status the OCO reaches after submission. Default ACTIVE. */
  ocoOutcome?: ProtectionStatus;
  /** Number of getOco() calls that still report PENDING before the outcome. */
  ocoActivationDelay?: number;
  /** submitOco throws BrokerRejectedError this many times first. */
  ocoSubmitRejections?: number;
  /** submitOco throws BrokerUncertainError (accepted but response lost) this many times first. */
  ocoSubmitTimeouts?: number;
}

interface PaperOrder {
  id: string;
  req: OrderRequest;
  status: OrderSnapshot["status"];
  rawStatus: string;
  triggered: boolean;
  fills: Fill[];
}

interface PaperOco {
  id: string;
  req: OcoRequest;
  status: ProtectionStatus;
  pendingPolls: number;
  finalStatus: ProtectionStatus;
}

export class PaperBroker implements BrokerPort, QuoteSource {
  readonly kind = "PAPER" as const;
  private seq = 0;
  private orders = new Map<string, PaperOrder>();
  private ocos = new Map<string, PaperOco>();
  private positions = new Map<string, number>();
  private fillSizes: number[];
  private ocoRejectionsLeft: number;
  private ocoTimeoutsLeft: number;

  constructor(
    private readonly clock: Clock,
    private readonly scenario: PaperScenario = {},
  ) {
    this.fillSizes = [...(scenario.entryFillSizes ?? [])];
    this.ocoRejectionsLeft = scenario.ocoSubmitRejections ?? 0;
    this.ocoTimeoutsLeft = scenario.ocoSubmitTimeouts ?? 0;
  }

  private id(prefix: string): string {
    return `${prefix}-${++this.seq}`;
  }

  async submitOrder(req: OrderRequest): Promise<OrderAck> {
    if (this.scenario.rejectEntry) throw new BrokerRejectedError(this.scenario.rejectEntry, "PAPER_REJECT");
    if (!(req.quantity > 0) || (req.orderType !== "MARKET" && !(req.price && req.price > 0))) throw new BrokerRejectedError("invalid order", "PAPER_INVALID");
    const o: PaperOrder = { id: this.id("PAPER-ORD"), req, status: "PENDING", rawStatus: "OPEN", triggered: req.orderType !== "SL", fills: [] };
    this.orders.set(o.id, o);
    if (this.scenario.entryTimeoutAfterAccept) throw new BrokerUncertainError("paper: response lost after acceptance", "TIMEOUT");
    return { brokerOrderId: o.id, clientRef: req.clientRef, rawStatus: o.rawStatus };
  }

  async modifyOrder(id: string, _segment: Segment, changes: { quantity: number; price?: number; triggerPrice?: number }): Promise<void> {
    const o = this.orders.get(id);
    if (!o || o.status !== "PENDING" && o.status !== "PARTIALLY_FILLED") throw new BrokerRejectedError("order not modifiable", "PAPER_STATE");
    o.req = { ...o.req, quantity: changes.quantity, price: changes.price ?? o.req.price, triggerPrice: changes.triggerPrice ?? o.req.triggerPrice };
  }

  async cancelOrder(id: string, _segment?: Segment): Promise<void> {
    const o = this.orders.get(id);
    if (!o) throw new BrokerRejectedError("order not found", "PAPER_404");
    if (o.status === "PENDING" || o.status === "PARTIALLY_FILLED") {
      o.status = "CANCELLED";
      o.rawStatus = "CANCELLED";
    }
  }

  private snapshot(o: PaperOrder): OrderSnapshot {
    const filled = o.fills.reduce((s, f) => s + f.quantity, 0);
    const avg = filled ? o.fills.reduce((s, f) => s + f.quantity * f.price, 0) / filled : undefined;
    return { brokerOrderId: o.id, clientRef: o.req.clientRef, status: o.status, rawStatus: o.rawStatus, orderedQuantity: o.req.quantity, reportedFilledQuantity: filled, averageFillPrice: avg };
  }

  async getOrder(id: string, _segment?: Segment): Promise<OrderSnapshot> {
    const o = this.orders.get(id);
    if (!o) throw new BrokerRejectedError("order not found", "PAPER_404");
    return this.snapshot(o);
  }

  async findOrderByClientRef(ref: string, _segment?: Segment): Promise<OrderSnapshot | null> {
    for (const o of this.orders.values()) if (o.req.clientRef === ref) return this.snapshot(o);
    return null;
  }

  async listFills(id: string, _segment?: Segment): Promise<Fill[]> {
    return [...(this.orders.get(id)?.fills ?? [])];
  }

  async getPosition(symbol: string, segment: Segment): Promise<PositionSnapshot> {
    return { tradingSymbol: symbol, segment, netQuantity: this.positions.get(symbol) ?? 0 };
  }

  async submitOco(req: OcoRequest): Promise<{ brokerOcoId: string; rawStatus: string }> {
    if (this.ocoRejectionsLeft > 0) {
      this.ocoRejectionsLeft--;
      throw new BrokerRejectedError("paper: OCO rejected", "PAPER_OCO_REJECT");
    }
    const actual = this.positions.get(req.instrument.tradingSymbol) ?? 0;
    const ok = req.quantity > 0 && req.quantity <= Math.abs(actual) && req.netPositionQuantity === actual;
    const oco: PaperOco = {
      id: this.id("PAPER-OCO"),
      req,
      status: "PENDING",
      pendingPolls: this.scenario.ocoActivationDelay ?? 0,
      finalStatus: ok ? (this.scenario.ocoOutcome ?? "ACTIVE") : "FAILED",
    };
    this.ocos.set(oco.id, oco);
    if (this.ocoTimeoutsLeft > 0) {
      this.ocoTimeoutsLeft--;
      throw new BrokerUncertainError("paper: OCO response lost after acceptance", "TIMEOUT");
    }
    return { brokerOcoId: oco.id, rawStatus: "PENDING" };
  }

  async modifyOco(id: string, _segment: Segment, changes: { quantity?: number; targetPrice?: number; stopTriggerPrice?: number }): Promise<void> {
    const oco = this.ocos.get(id);
    if (!oco || (oco.status !== "ACTIVE" && oco.status !== "PENDING")) throw new BrokerRejectedError("OCO not modifiable", "PAPER_STATE");
    const actual = Math.abs(this.positions.get(oco.req.instrument.tradingSymbol) ?? 0);
    if (changes.quantity !== undefined && changes.quantity > actual) throw new BrokerRejectedError("OCO quantity above position", "PAPER_QTY");
    oco.req = {
      ...oco.req,
      quantity: changes.quantity ?? oco.req.quantity,
      targetPrice: changes.targetPrice ?? oco.req.targetPrice,
      stopTriggerPrice: changes.stopTriggerPrice ?? oco.req.stopTriggerPrice,
    };
  }

  async cancelOco(id: string, _segment?: Segment): Promise<void> {
    const oco = this.ocos.get(id);
    if (oco && (oco.status === "ACTIVE" || oco.status === "PENDING")) oco.status = "CANCELLED";
  }

  private ocoSnap(o: PaperOco): OcoSnapshot {
    return { brokerOcoId: o.id, clientRef: o.req.clientRef, status: o.status, rawStatus: o.status, quantity: o.req.quantity };
  }

  async getOco(id: string, _segment?: Segment): Promise<OcoSnapshot> {
    const o = this.ocos.get(id);
    if (!o) throw new BrokerRejectedError("OCO not found", "PAPER_404");
    if (o.status === "PENDING") {
      if (o.pendingPolls > 0) o.pendingPolls--;
      else o.status = o.finalStatus;
    }
    return this.ocoSnap(o);
  }

  async findOcoByClientRef(ref: string, _segment?: Segment): Promise<OcoSnapshot | null> {
    for (const o of this.ocos.values()) if (o.req.clientRef === ref) return this.ocoSnap(o);
    return null;
  }

  /** Drives the simulation with a last traded price. */
  tick(symbol: string, ltp: number): void {
    const at = this.clock.now().toISOString();
    this.lastPrice.set(symbol, { price: ltp, at });
    for (const o of this.orders.values()) {
      if (o.req.instrument.tradingSymbol !== symbol || (o.status !== "PENDING" && o.status !== "PARTIALLY_FILLED")) continue;
      const buy = o.req.side === "BUY";
      if (!o.triggered) {
        if (o.req.triggerPrice === undefined || (buy ? ltp >= o.req.triggerPrice : ltp <= o.req.triggerPrice)) o.triggered = true;
        else continue;
      }
      const limit = o.req.price ?? ltp;
      if (o.req.orderType !== "MARKET" && (buy ? ltp > limit : ltp < limit)) continue;
      const filled = o.fills.reduce((s, f) => s + f.quantity, 0);
      const remaining = o.req.quantity - filled;
      const q = Math.min(remaining, this.fillSizes.shift() ?? remaining);
      o.fills.push({ brokerTradeId: this.id("PAPER-TRD"), brokerOrderId: o.id, quantity: q, price: o.req.orderType === "MARKET" ? ltp : buy ? Math.min(ltp, limit) : Math.max(ltp, limit), at });
      this.positions.set(symbol, (this.positions.get(symbol) ?? 0) + (buy ? q : -q));
      const now = filled + q;
      o.status = now >= o.req.quantity ? "FILLED" : "PARTIALLY_FILLED";
      o.rawStatus = now >= o.req.quantity ? "EXECUTED" : "OPEN";
    }
    for (const oco of this.ocos.values()) {
      if (oco.req.instrument.tradingSymbol !== symbol || oco.status !== "ACTIVE") continue;
      const sellExit = oco.req.exitSide === "SELL";
      const hitTarget = sellExit ? ltp >= oco.req.targetPrice : ltp <= oco.req.targetPrice;
      const hitStop = sellExit ? ltp <= oco.req.stopTriggerPrice : ltp >= oco.req.stopTriggerPrice;
      if (!hitTarget && !hitStop) continue;
      const pos = this.positions.get(symbol) ?? 0;
      const q = Math.min(oco.req.quantity, Math.abs(pos));
      this.positions.set(symbol, pos + (sellExit ? -q : q));
      oco.status = "COMPLETED";
      this.lastExit.set(oco.id, { price: hitTarget ? oco.req.targetPrice : ltp, quantity: q, leg: hitTarget ? "TARGET" : "STOP" });
    }
  }

  private lastExit = new Map<string, { price: number; quantity: number; leg: "TARGET" | "STOP" }>();

  async describeExit(ocoId: string): Promise<{ price: number; quantity: number; leg: "TARGET" | "STOP" } | undefined> {
    return this.lastExit.get(ocoId);
  }

  /** Paper quote source: the last price passed to tick(). */
  private lastPrice = new Map<string, { price: number; at: string }>();
  async getLtp(inst: Instrument): Promise<{ price: number; at: string }> {
    const q = this.lastPrice.get(inst.tradingSymbol);
    if (!q) throw new BrokerRejectedError(`paper: no price yet for ${inst.tradingSymbol}`, "NO_QUOTE");
    return q;
  }

  /** Test hook: simulate an external change to the position (e.g. a manual trade in the app). */
  _setPositionForTest(symbol: string, qty: number): void {
    this.positions.set(symbol, qty);
  }
}

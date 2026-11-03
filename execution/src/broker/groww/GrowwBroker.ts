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
} from "../../domain/types.js";
import { BrokerError, BrokerRejectedError, BrokerShapeError, type BrokerPort, type QuoteSource } from "../BrokerPort.js";
import type { GrowwHttp } from "./http.js";
import { parseOrderDetail, parseOrderIdByRef, parseQuote, parsePositionQty, parseSmartOrder, parseSmartOrderList, parseTrades } from "./mapping.js";

/**
 * Everything that changes state at Groww (orders and smart orders) sits behind this interface, implemented in
 * orders.ts. GrowwBroker itself only reads. The composition root (main.ts) builds the writer only after the
 * live gate passes.
 */
export interface GrowwOrderWriter {
  submitOrder(req: OrderRequest): Promise<OrderAck>;
  modifyOrder(brokerOrderId: string, segment: Segment, changes: { quantity: number; price?: number; triggerPrice?: number; orderType: OrderRequest["orderType"] }): Promise<void>;
  cancelOrder(brokerOrderId: string, segment: Segment): Promise<void>;
  submitOco(req: OcoRequest): Promise<{ brokerOcoId: string; rawStatus: string }>;
  modifyOco(brokerOcoId: string, segment: Segment, changes: { quantity?: number; targetPrice?: number; stopTriggerPrice?: number }): Promise<void>;
  cancelOco(brokerOcoId: string, segment: Segment): Promise<void>;
}

export class LiveOrdersDisabled extends BrokerRejectedError {
  constructor() {
    super("Groww order placement is not enabled in this build/process", "LIVE_DISABLED");
    this.name = "LiveOrdersDisabled";
  }
}

/** Default writer: refuses everything. Used for read-only probes and whenever the gate has not passed. */
export const disabledWriter: GrowwOrderWriter = {
  submitOrder: async () => {
    throw new LiveOrdersDisabled();
  },
  modifyOrder: async () => {
    throw new LiveOrdersDisabled();
  },
  cancelOrder: async () => {
    throw new LiveOrdersDisabled();
  },
  submitOco: async () => {
    throw new LiveOrdersDisabled();
  },
  modifyOco: async () => {
    throw new LiveOrdersDisabled();
  },
  cancelOco: async () => {
    throw new LiveOrdersDisabled();
  },
};

function notFound(e: unknown): boolean {
  return e instanceof BrokerRejectedError && (e.code === "404" || /not\s*found/i.test(e.message));
}

const PAGE = 50;

export class GrowwBroker implements BrokerPort, QuoteSource {
  readonly kind = "GROWW" as const;

  constructor(
    private readonly http: GrowwHttp,
    private readonly writer: GrowwOrderWriter = disabledWriter,
  ) {}

  // ---- writes (delegated) -------------------------------------------------------------------------------
  submitOrder(req: OrderRequest): Promise<OrderAck> {
    return this.writer.submitOrder(req);
  }
  modifyOrder(id: string, segment: Segment, changes: { quantity: number; price?: number; triggerPrice?: number; orderType: OrderRequest["orderType"] }): Promise<void> {
    return this.writer.modifyOrder(id, segment, changes);
  }
  cancelOrder(id: string, segment: Segment): Promise<void> {
    return this.writer.cancelOrder(id, segment);
  }
  submitOco(req: OcoRequest): Promise<{ brokerOcoId: string; rawStatus: string }> {
    return this.writer.submitOco(req);
  }
  modifyOco(id: string, segment: Segment, changes: { quantity?: number; targetPrice?: number; stopTriggerPrice?: number }): Promise<void> {
    return this.writer.modifyOco(id, segment, changes);
  }
  cancelOco(id: string, segment: Segment): Promise<void> {
    return this.writer.cancelOco(id, segment);
  }

  // ---- reads --------------------------------------------------------------------------------------------
  async getOrder(id: string, segment: Segment): Promise<OrderSnapshot> {
    return parseOrderDetail(await this.http.get(`/order/detail/${encodeURIComponent(id)}`, { segment }));
  }

  async findOrderByClientRef(ref: string, segment: Segment): Promise<OrderSnapshot | null> {
    let id: string;
    try {
      id = parseOrderIdByRef(await this.http.get(`/order/status/reference/${encodeURIComponent(ref)}`, { segment }));
    } catch (e) {
      if (notFound(e)) return null;
      throw e;
    }
    return this.getOrder(id, segment);
  }

  async listFills(id: string, segment: Segment): Promise<Fill[]> {
    const out: Fill[] = [];
    for (let page = 0; page < 20; page++) {
      const batch = parseTrades(await this.http.get(`/order/trades/${encodeURIComponent(id)}`, { segment, page, page_size: PAGE }), id);
      out.push(...batch);
      if (batch.length < PAGE) return out;
    }
    throw new BrokerError("trade list longer than 1000 rows; refusing to guess", "PAGING");
  }

  async getPosition(tradingSymbol: string, segment: Segment): Promise<PositionSnapshot> {
    const payload = await this.http.get("/positions/trading-symbol", { trading_symbol: tradingSymbol, segment });
    return { tradingSymbol, segment, netQuantity: parsePositionQty(payload, tradingSymbol) };
  }

  async getOco(id: string, segment: Segment): Promise<OcoSnapshot> {
    return parseSmartOrder(await this.http.get(`/order-advance/status/${segment}/OCO/internal/${encodeURIComponent(id)}`));
  }

  async findOcoByClientRef(ref: string, segment: Segment): Promise<OcoSnapshot | null> {
    for (let page = 0; page < 10; page++) {
      const list = parseSmartOrderList(await this.http.get("/order-advance/list", { smart_order_type: "OCO", segment, page, page_size: PAGE }));
      if (list.length && list.every((o) => o.clientRef === undefined)) {
        throw new BrokerShapeError("smart order list has no reference_id field; cannot look up by reference");
      }
      const hit = list.find((o) => o.clientRef === ref);
      if (hit) return hit;
      if (list.length < PAGE) return null;
    }
    throw new BrokerError("smart order list too long to search", "PAGING");
  }

  async getLtp(inst: Instrument): Promise<{ price: number; at: string }> {
    return parseQuote(await this.http.get("/live-data/quote", { exchange: inst.exchange, segment: inst.segment, trading_symbol: inst.tradingSymbol }));
  }
}

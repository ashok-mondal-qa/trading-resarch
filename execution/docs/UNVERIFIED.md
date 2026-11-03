# What is and is not verified about the Groww API (2026-11-03)

`groww.in` and `api.groww.in` are blocked by the build environment's network proxy, so nothing here was checked
against Groww's live documentation or a real account. Every item below must be ticked off before LIVE_APPROVAL
is considered. `npm run groww:probe -- <SYMBOL> [ORDER_ID]` (read-only, prints field names only) on the
deployment machine checks most of them.

## Source used
Groww's official Python SDK `growwapi` **1.5.0** (PyPI, published 2025-12-06, "Copyright (c) 2025 Groww
(India)", MIT licence), wheel sha256 `b4871ed19415b6ad7434bee2178f53aa1e180fbddd4a25693c458440f66939cc`.
Read as source only; not executed. The SDK fixes **paths, methods and request bodies**. It does **not**
describe response bodies.

## Verified from the SDK source (paths and requests)
| Item | Value |
| --- | --- |
| Base URL | `https://api.groww.in/v1` |
| Token | `POST /token/api/access`, `Authorization: Bearer <api key>`, body `{key_type: "approval", checksum: sha256(secret + timestamp), timestamp}` or `{key_type: "totp", totp}`; response field `token` |
| Envelope | `{"status": "SUCCESS", "payload": ...}` / `{"status": "FAILURE", "error": {"code", "message"}}`; HTTP 400/401/403/404/429/504 mapped to errors |
| Place order | `POST /order/create` body `trading_symbol, quantity, price, trigger_price, validity, exchange, segment, product, order_type, transaction_type, order_reference_id` |
| Modify / cancel order | `POST /order/modify` (`quantity, price, trigger_price, groww_order_id, order_type, segment`), `POST /order/cancel` (`segment, groww_order_id`) |
| Order reads | `GET /order/detail/{id}?segment=`, `GET /order/status/{id}?segment=`, `GET /order/status/reference/{ref}?segment=`, `GET /order/trades/{id}?segment=&page=&page_size=`, `GET /order/list` |
| Positions | `GET /positions/trading-symbol?trading_symbol=&segment=`, `GET /positions/user?segment=` |
| Quote | `GET /live-data/quote` (params per SDK: exchange, segment, trading_symbol), `GET /live-data/ltp` |
| Smart orders | `POST /order-advance/create`; `PUT /order-advance/modify/{id}`; `POST /order-advance/cancel/{segment}/{type}/{id}`; `GET /order-advance/status/{segment}/{type}/internal/{id}`; `GET /order-advance/list` (`smart_order_type, segment, status, page (0-500), page_size (1-50), start_date_time, end_date_time`) |
| OCO create body | `smart_order_type: "OCO", reference_id, segment, trading_symbol, quantity, product_type, exchange, duration, net_position_quantity, target {trigger_price, order_type, price?}, stop_loss {trigger_price, order_type, price?}, transaction_type` |
| Smart-order statuses | `ACTIVE, TRIGGERED, CANCELLED, EXPIRED, FAILED, COMPLETED` |
| Constants | segments `CASH, FNO`; products `CNC, MIS, NRML`; order types `LIMIT, MARKET, SL, SL_M`; validity `DAY, IOC, ...` |

## NOT verified (best recollection; the code fails safe if wrong)
| Item | Assumed | If wrong |
| --- | --- | --- |
| Order response fields | `groww_order_id, order_status, quantity, filled_quantity, average_fill_price, remark, order_reference_id` | Parser throws → state UNKNOWN → no fill or protection assumed |
| `order_status` values | pending: `NEW, ACKED, OPEN, TRIGGER_PENDING, APPROVED, MODIFICATION_REQUESTED, CANCELLATION_REQUESTED`; done: `EXECUTED, COMPLETED, DELIVERY_AWAITED`; `REJECTED, FAILED, CANCELLED` | Unknown value → UNKNOWN (waits, never assumes) |
| Trade list | `{trade_list: [{groww_trade_id, quantity, price, trade_date_time}]}` | Parser throws → no fills counted |
| Positions | `{positions: [{trading_symbol, quantity, product}]}`, `quantity` = signed net | Parser throws → entry refused (DATA INSUFFICIENT) |
| Quote | `last_price`, `last_trade_time` (epoch ms or s) | Parser throws → approval re-check fails → not sent |
| Smart order fields | `smart_order_id, status, quantity, reference_id`; list under `orders` | Parser throws → OCO treated as unconfirmed; lookup errors never trigger a duplicate OCO |
| OCO leg prices | decimal strings (SDK says so for GTT `trigger_price`) | Groww rejects → retry → PROTECTION_FAILED → exit approval |
| OCO leg order types | target `LIMIT` at the target price; stop `SL_M` at the stop trigger | as above |
| `order_reference_id` format | 16 upper-case alphanumerics (SDK default is an 8-digit number) | Groww rejects the entry → ENTRY_REJECTED, nothing open |
| Token expiry | daily at 06:00 IST | 401 → one refresh + retry, then auth error |
| Idempotency | Groww does not de-duplicate by reference; the engine never resends | — |
| Rate limits | not modelled; the engine makes a few calls per 3 s cycle | 429 on a write is treated as UNCERTAIN (looked up, never resent) |
| Charges | see `src/risk/charges.ts` (`verified: false`), 25% buffer | Check against Groww's pricing page and one real contract note |

## Regulatory items to confirm (not legal advice)
SEBI's retail algorithmic-trading framework (circular of 4 Feb 2025, phased in by brokers through 2025-26) is
the relevant rulebook for API order placement by individuals. Items to confirm with Groww before any live use:
whether a static IP must be registered for API order placement, whether orders need an exchange algo id or tag,
whether an approval-per-order workflow below the orders-per-second threshold counts as a registered "algo", and
the API terms of use. None of this was checked here.

-- Execution engine schema v1 (PostgreSQL 16).
-- Money-guarding rules live in constraints, not only in application code:
--   * one trade per (mode, IST trading day): primary key on daily_slots
--   * approvals are single use: status moves out of PENDING exactly once (guarded UPDATE in the app,
--     CHECK + trigger here)
--   * the audit trail is append-only: UPDATE / DELETE / TRUNCATE raise

CREATE TABLE IF NOT EXISTS daily_slots (
  mode         text NOT NULL CHECK (mode IN ('PAPER', 'LIVE_APPROVAL')),
  trading_day  text NOT NULL CHECK (trading_day ~ '^\d{4}-\d{2}-\d{2}$'),
  trade_id     text NOT NULL,
  claimed_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (mode, trading_day)
);

CREATE TABLE IF NOT EXISTS trades (
  trade_id     text PRIMARY KEY,
  mode         text NOT NULL CHECK (mode IN ('PAPER', 'LIVE_APPROVAL')),
  trading_day  text NOT NULL,
  state        text NOT NULL,
  version      integer NOT NULL CHECK (version >= 1),
  record       jsonb NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trades_open_idx ON trades (mode, state);

CREATE TABLE IF NOT EXISTS approvals (
  approval_id          text PRIMARY KEY,
  trade_id             text NOT NULL REFERENCES trades (trade_id),
  kind                 text NOT NULL CHECK (kind IN ('ENTRY', 'EXIT')),
  intent_hash          char(64) NOT NULL,
  nonce_hash           char(64) NOT NULL,
  status               text NOT NULL CHECK (status IN ('PENDING', 'APPROVED', 'DENIED', 'EXPIRED')),
  expires_at           timestamptz NOT NULL,
  created_at           timestamptz NOT NULL,
  decided_at           timestamptz,
  decided_by           text,
  telegram_message_id  bigint
);
CREATE UNIQUE INDEX IF NOT EXISTS approvals_one_pending_per_trade ON approvals (trade_id) WHERE status = 'PENDING';

CREATE OR REPLACE FUNCTION approvals_single_use() RETURNS trigger AS $$
BEGIN
  IF OLD.status <> 'PENDING' AND NEW.status <> OLD.status THEN
    RAISE EXCEPTION 'approval % already decided (%), approvals are single use', OLD.approval_id, OLD.status;
  END IF;
  IF NEW.intent_hash <> OLD.intent_hash OR NEW.nonce_hash <> OLD.nonce_hash OR NEW.trade_id <> OLD.trade_id OR NEW.kind <> OLD.kind THEN
    RAISE EXCEPTION 'approval % binding fields are immutable', OLD.approval_id;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS approvals_single_use_trg ON approvals;
CREATE TRIGGER approvals_single_use_trg BEFORE UPDATE ON approvals
  FOR EACH ROW EXECUTE FUNCTION approvals_single_use();

CREATE TABLE IF NOT EXISTS audit_events (
  seq        bigserial PRIMARY KEY,
  at         text NOT NULL,           -- ISO 8601 string exactly as hashed
  trade_id   text,
  type       text NOT NULL,
  payload    jsonb NOT NULL,
  prev_hash  char(64) NOT NULL,
  hash       char(64) NOT NULL UNIQUE,
  stored_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_trade_idx ON audit_events (trade_id, seq);

CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only';
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_no_update ON audit_events;
CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION audit_append_only();
DROP TRIGGER IF EXISTS audit_no_truncate ON audit_events;
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_events
  FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only();

CREATE TABLE IF NOT EXISTS kv (
  key         text PRIMARY KEY,
  value       text NOT NULL,
  updated_at  timestamptz NOT NULL DEFAULT now()
);

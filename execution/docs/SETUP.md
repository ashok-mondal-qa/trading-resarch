# Setup and deployment

Runs anywhere with Docker (a home PC that stays on during market hours, or a small VPS in India). PAPER mode
needs no Groww account; Groww keys only add real quotes for the paper fills.

## 1. Telegram bot (owner, ~5 minutes)
1. In Telegram, open **@BotFather**, send `/newbot`, pick a name. Copy the token it shows.
2. Open your new bot and press **Start** (the bot can only message you after this).
3. Open **@userinfobot**, press Start, copy the number after `Id`. In a private chat with the bot, your chat id
   is the same number.
4. Put the token in `execution/secrets/telegram_bot_token` (a file with just the token). Never paste it into
   chat. Put the id in `.env` as both `TELEGRAM_ALLOWED_CHAT_ID` and `TELEGRAM_ALLOWED_USER_IDS`.
5. Turn on Telegram two-step verification: anyone with your Telegram account can approve trades.

## 2. Groww API key (optional for PAPER)
1. Log in at groww.in, open the Trade API page, and generate an API key and secret (Groww may charge for API
   access; check the page).
2. Save them as `execution/secrets/groww_api_key` and `execution/secrets/groww_api_secret`.
3. For PAPER without Groww, leave both files empty; post prices to the intake `/quotes` endpoint instead.

## 3. Run (PAPER)
```
cd execution
cp .env.example .env               # edit TELEGRAM_ALLOWED_* ids
mkdir -p secrets
openssl rand -hex 24 > secrets/db_password
openssl rand -hex 24 > secrets/intake_token
# telegram_bot_token, groww_api_key, groww_api_secret from steps 1-2
chmod 600 secrets/*
docker compose up -d --build
docker compose logs -f engine      # expect "starting" and a Telegram "Execution engine started in PAPER mode"
```

## 4. Send a proposal (what the daily scan will do)
```
curl -s -X POST http://127.0.0.1:8787/proposals \
  -H "Authorization: Bearer $(cat secrets/intake_token)" -H "Content-Type: application/json" \
  -d @proposal.json
```
`proposal.json` follows `TradeProposal` in `src/domain/types.ts`. The engine replies with the trade id and state.
If the risk engine passes it, Telegram shows the setup with **Approve entry / Reject** buttons (one use,
90 s). On approval it re-checks with a fresh quote and only then sends the (paper) order.

## 5. Operator commands
```
docker compose exec engine node dist/cli.js status
docker compose exec engine node dist/cli.js verify-audit
docker compose exec engine node dist/cli.js gate           # why LIVE is closed
docker compose exec engine node dist/cli.js clear-halt "reviewed incident: position matched app, OCO active"
```
In Telegram: `/status`, `/halt` (blocks new entries; only the server can clear it).

## 6. Tests
```
npm ci && npm run typecheck && npm run build
TEST_DATABASE_URL=postgres://user@127.0.0.1:5432/exec_test npm test
```

## 7. LIVE_APPROVAL (not available in this build)
Requires, all at once: a strategy ACCEPTED in `experiments/registry.csv`, `npm run safety:attest` passing on the
deployed commit, at least 20 complete paper workflows with no open safety incidents, every item in
`docs/UNVERIFIED.md` checked, `LIVE_TRADING_ENABLED=true`, the exact `LIVE_TRADING_ACK` phrase from
`src/config/liveGate.ts`, and the owner's explicit written go-ahead. This build also has no Groww order writer,
so LIVE refuses to start even if the gate passes.

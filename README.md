# dhan-algo

Automated NSE options strategies on [Dhan](https://dhan.co) — top-mover ATM options, BTST Nifty, and more. Strategies are configured in git and run on a schedule or manually.

## Prerequisites

- Python 3.10+ and [uv](https://docs.astral.sh/uv/) (local dev)
- Dhan API credentials (`DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`)
- Active Dhan **Data API** plan (quotes, option chain, intraday history)
- **Static IP whitelisted** on Dhan for order placement (required for live trades)
- Optional: Telegram bot token + chat ID for trade alerts

## Setup (local)

```bash
git clone https://github.com/Vishal-Isharani/dhan-algo.git
cd dhan-algo

cp .env.example .env
# Edit .env with your Dhan credentials

uv sync
```

### Configure strategies

1. Copy the manifest if you don't have one yet:

   ```bash
   cp strategies/manifest.example.json strategies/manifest.json
   ```

2. Add or copy strategy config files under `strategies/configs/` (see `*.example.json` files).

3. Enable/disable strategies in `strategies/manifest.json`:

   ```json
   {
     "name": "btst-nifty",
     "type": "btst_nifty",
     "config": "btst_nifty.json",
     "enabled": true
   }
   ```

Each config file sets `run_at` (IST, `HH:MM` or `HH:MM:SS`) and strategy-specific params (lots, product, etc.).

## Run strategies manually (local)

Use `--now` to skip waiting for the config's `run_at` time (useful for testing).

```bash
# One strategy instance (name from manifest.json)
uv run run-strategies --now btst-nifty
uv run run-strategies --now top-mover-loosers

# Multiple instances
uv run run-strategies --now btst-nifty top-mover-gainers

# All enabled strategies in manifest (waits until each run_at unless --now)
uv run run-strategies
```

Other commands:

```bash
# Preview what the scheduler would run today
uv run run-scheduler --list

# BTST next-morning exit (for open btst_nifty positions)
uv run run-btst-exit --now

# Trade history / P&L summary
uv run trade-report
```

## Run on VPS (Dokploy)

Production uses the **scheduler** — it checks NSE trading days and launches strategies at their `run_at` times. BTST exits run automatically at 09:13 IST on trading days.

### Deploy

1. In Dokploy: **New project** → **Compose** → type **Docker Compose** (not Stack).
2. Connect this repo; set compose path to `./docker-compose.yml`.
3. In **Environment**, set:
   - `DHAN_CLIENT_ID`
   - `DHAN_ACCESS_TOKEN`
   - `TELEGRAM_BOT_TOKEN` (optional)
   - `TELEGRAM_CHAT_ID` (optional)
4. Deploy. The scheduler container runs `run-scheduler` and restarts on failure.

No domain or Traefik setup is needed — this is a background worker, not a web app.

### Config changes on VPS

Edit locally, commit, push, redeploy:

- `strategies/manifest.json` — enable/disable strategy instances
- `strategies/configs/*.json` — per-strategy settings (`run_at`, lots, etc.)

These files are baked into the Docker image on each deploy. Only runtime data (trades DB, scheduler state, NSE cache) lives in Docker volumes.

### Verify deployment

In the Dokploy container terminal:

```bash
run-scheduler --list
cat strategies/manifest.json
ls strategies/configs/
```

### Run strategies manually on VPS

From the Dokploy terminal (inside the running container):

```bash
# Skip wait — run immediately
run-strategies --now btst-nifty
run-strategies --now top-mover-loosers

# BTST morning exit
run-btst-exit --now

# Trade report
trade-report
```

Or one-off from the host (if you have shell access to the VPS):

```bash
docker compose -p <your-dokploy-project> exec scheduler run-strategies --now btst-nifty
```

Replace `<your-dokploy-project>` with your Dokploy compose project name (e.g. `option-algo-be-zxmu4m`).

## Scheduler behaviour (production)

Each trading day (IST):

| Time | Action |
|------|--------|
| 09:10 | Confirm NSE trading day (weekday + not holiday) |
| Per strategy | Launch enabled instances at `run_at` from config |
| 09:13 | Launch BTST exit job for open `btst_nifty` positions |

State is stored in `data/scheduler_state.json`. Trades are logged to `data/trades.db`.

## Available strategies

| Type | Description |
|------|-------------|
| `top_mover_options` | Buy ATM CE/PE on NSE F&O top gainer/loser |
| `btst_nifty` | Nifty BTST — entry ~15:20, exit next morning |
| `btst_sensex` | Placeholder (not implemented) |

## Dhan IP whitelist

Order APIs require your **server's public IP** whitelisted on Dhan. The app attempts auto-whitelist on startup via `scripts/ip_manager.py`. If orders fail with IP errors, whitelist the VPS egress IP manually in the Dhan developer portal.

## Project layout

```
strategies/
  manifest.json          # Which strategies to run (enable/disable here)
  configs/               # One JSON file per strategy instance
scripts/
  scheduler.py           # Trading-day scheduler
  btst_exit.py           # BTST morning exit logic
run_strategy.py          # CLI: run-strategies
run_scheduler.py         # CLI: run-scheduler
run_btst_exit.py         # CLI: run-btst-exit
docker-compose.yml       # Dokploy / Docker production
```

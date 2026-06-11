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

# Trade history / P&L summary (sync with Dhan first if you closed manually)
uv run trade-report --sync

# Or reconcile open trades only
uv run run-reconcile-trades
```

## Dashboard

A web dashboard lets you toggle strategies, edit configs, view P&L, and export trades — **without redeploying**.

```bash
# Local
export DASHBOARD_API_KEY=your_secret   # optional locally; required in production
uv run run-dashboard
# Open http://localhost:8080
```

On first run, configs are copied from `strategies/` into `data/strategy_config/` (volume-mounted in Docker). The scheduler and dashboard both read from `data/strategy_config/`, so changes via the UI take effect on the next scheduled run.

**Tabs:**
- **Overview** — P&L summary, open positions, today's schedule
- **Strategies** — enable/disable instances, edit JSON config (validated on save)
- **Reports** — trade history, filter by strategy, sync with Dhan, export CSV

Set `DASHBOARD_API_KEY` in `.env` and enter the same key in the dashboard settings (⚙) when prompted.

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

The **dashboard** service exposes port `8080`. Point a Dokploy domain at it (or access via VPS IP) and set `DASHBOARD_API_KEY` in Environment.

### Config changes on VPS

**Preferred:** use the dashboard to toggle strategies and edit configs — saved to `data/strategy_config/` (persists in the `dhan_algo_data` volume, no redeploy).

**Alternatively:** edit `strategies/manifest.json` and `strategies/configs/*.json` locally, commit, push, redeploy (seeds defaults on first dashboard/scheduler start if runtime config is empty).

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

Event-driven — sleeps until the next job, not polling every 30 seconds.

Each trading day (IST):

| Time | Action |
|------|--------|
| 09:10 | Wake — confirm NSE trading day (weekday + not holiday) |
| 09:13 | Wake — BTST exit job (if open `btst_nifty` positions) |
| Per strategy | Wake at each enabled instance's `run_at` from config |
| 15:30 | Sleep until next trading morning (09:10) |

On holidays/weekends the scheduler sleeps from 09:10 until the next weekday morning.

Failed runs are **not** retried — one attempt per strategy per day. Re-run manually with `run-strategies --now <name>` if needed.

Each strategy runs only within **3 minutes** of its scheduled `run_at`. Redeploy/restart after that window will not catch up. If a trade was already logged today in `trades.db`, duplicate entry is blocked even if scheduler state was reset.

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
  manifest.json          # Default strategy manifest (seed for runtime config)
  configs/               # Default per-instance configs
data/
  strategy_config/       # Runtime configs (dashboard edits; volume-mounted)
  trades.db              # Trade journal
  scheduler_state.json   # Scheduler daily state
dashboard/
  app.py                 # FastAPI API + static UI
  static/index.html
scripts/
  config_store.py        # Read/write runtime strategy config
  scheduler.py           # Trading-day scheduler
run_dashboard.py         # CLI: run-dashboard
run_strategy.py          # CLI: run-strategies
run_scheduler.py         # CLI: run-scheduler
docker-compose.yml       # Dokploy / Docker production (scheduler + dashboard)
```

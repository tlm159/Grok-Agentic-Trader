# Grok-Agentic-Trader

Autonomous Grok-powered trading bot (paper trading) with a lightweight real-time UI.

## How it works

```mermaid
flowchart TD
  A[Market data via yfinance] --> B[Session gate (NY hours + cutoff)]
  B -->|In session| C[Live search]
  B -->|Out of session| H[Auto HOLD + logs]
  C --> D[LLM decision: Grok]
  D --> E{BUY / SELL / HOLD}
  E -->|Trade| F[Paper broker]
  F --> G[Portfolio state]
  E -->|Hold| G
  G --> I[Dashboard JSON]
  I --> J[UI (real-time)]
  D --> K[Decision log]
  F --> K
  L[Price loop] --> I
```

## Quickstart

1) Install deps:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Add your API key:
```bash
cp .env.example .env
# then edit .env
```

3) Run once:
```bash
python src/main.py
```

## Live UI

This lightweight UI reads `data/dashboard.json` and auto-refreshes.

1) Run the bot loop in one terminal:
```bash
python src/loop.py
```

2) Serve the UI in another terminal:
```bash
python -m http.server 8000
```

Open `http://localhost:8000/ui/simple/`.

Or run both with one command:

```bash
./scripts/run_simple_live.sh
```

Or run the bot once and then open the UI:

```bash
./scripts/run_dashboard.sh
```

Or run the bot in a loop and keep the UI auto-refreshing:

```bash
./scripts/run_live.sh
```

The live scripts also run a lightweight price loop (no AI) to refresh PnL in real time.

## Trading rules (current behavior)

- US-listed equities only (crypto/FX blocked).
- New York session only (auto-handles DST; shown in Paris time).
- No new positions 30 minutes before NY close.
- All open positions are closed at NY close (22:00 FR).
- No trading on weekends.
- BUY requires both SL/TP; Grok can adjust SL/TP via HOLD.
- Decision loop runs every `cycle_minutes` (default 30 min).

## Live search and cost control

You can keep live search on while limiting costs:
- `live_search.max_queries_per_run`: limit queries per cycle
- `live_search.cooldown_minutes`: reuse cached results for this long
- `live_search.max_sources`: sources per query (each source is billed)

## Live Search (optional)

The bot can optionally call xAI live search to pull recent market context.

1) Enable in `config/settings.json`:
```json
\"live_search\": { \"enabled\": true }
```

2) Install the SDK:
```bash
pip install -r requirements.txt
```

Note: live search uses extra paid sources. You are billed by xAI for live search usage.

## Config

- `config/settings.json`: model, base_url, trade mode (paper), and risk flags.
- `config/settings.json` also controls `starting_cash` if no state exists yet.
- Runtime data is stored in `data/` (state, trades, dashboard), but it is ignored by git.

## Notes

- Prices come from Yahoo Finance via `yfinance`.
- The bot chooses any US-listed ticker it wants (crypto/FX are blocked).
- `scripts/run_live.sh` includes a lockfile to prevent multiple loops and avoid extra API costs.
- Text logs are written to `data/run.log` for quick inspection without the UI.
  - Live tail: `tail -f data/run.log`

## Disclaimer

Educational use only. Not financial advice.

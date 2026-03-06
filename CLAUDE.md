# CLAUDE.md

This file provides guidance for AI assistants (Claude and others) working in this repository.

## Repository Overview

**多交易所辅助工具** — A local web-based assistant for managing multiple cryptocurrency exchange accounts from a single interface. Eliminates the need to manually operate each exchange's website.

### Supported Features
- **下单** — Place market or limit orders (buy/sell)
- **提币** — Withdraw coins to external addresses
- **借币** — Borrow and repay margin loans (cross or isolated)
- **循环借币** — Automated loop borrowing (geometric series of borrow rounds to amplify effective exposure)

### Supported Exchanges
Binance, OKX, Bybit, Gate.io, KuCoin (via the [ccxt](https://github.com/ccxt/ccxt) library)

---

## Project Structure

```
aitest/
├── main.py              # FastAPI backend — all REST API endpoints
├── requirements.txt     # Python dependencies
├── static/
│   └── index.html       # Single-page frontend (Bootstrap 5 + vanilla JS)
├── config.json          # API keys — NEVER commit this file (in .gitignore)
├── .gitignore
└── CLAUDE.md
```

---

## Tech Stack

| Layer    | Technology                       |
|----------|----------------------------------|
| Backend  | Python · FastAPI · uvicorn       |
| Exchange | ccxt ≥ 4.0                       |
| Frontend | Bootstrap 5.3 · vanilla JS       |
| Storage  | Local `config.json` (not in git) |

---

## Build & Run

### Install dependencies

```bash
pip install -r requirements.txt
```

### Start the server

```bash
python main.py
# or with auto-reload during development:
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in a browser.

### First-time setup

1. Click the gear icon (⚙) in the top-right
2. Select an exchange and enter your API Key + Secret (+ Passphrase for OKX/KuCoin)
3. Click **保存**
4. Select the exchange from the top dropdown

---

## API Endpoints

| Method | Path                                  | Description           |
|--------|---------------------------------------|-----------------------|
| GET    | `/api/exchanges`                      | List supported/configured exchanges |
| POST   | `/api/exchanges/{eid}`                | Save/update API credentials |
| DELETE | `/api/exchanges/{eid}`                | Remove exchange config |
| GET    | `/api/balances/{eid}?type=spot`       | Fetch account balances |
| POST   | `/api/orders`                         | Place an order        |
| GET    | `/api/orders/{eid}?symbol=BTC/USDT`   | List open orders      |
| DELETE | `/api/orders/{eid}/{id}?symbol=…`     | Cancel an order       |
| POST   | `/api/withdraw`                       | Withdraw coins        |
| POST   | `/api/transfer`                       | Transfer between accounts |
| POST   | `/api/borrow`                         | Borrow margin         |
| POST   | `/api/repay`                          | Repay margin loan     |
| POST   | `/api/loop-borrow/start`              | Start loop borrow task |
| GET    | `/api/loop-borrow/tasks`              | List all tasks        |
| GET    | `/api/loop-borrow/tasks/{tid}`        | Get task detail + log |
| POST   | `/api/loop-borrow/tasks/{tid}/stop`   | Signal task to stop   |

---

## Loop Borrow Logic

Loop borrowing executes N rounds of margin borrowing in a **geometric series**:

- Round 1: `initial × ratio`
- Round 2: `initial × ratio²`
- Round n: `initial × ratioⁿ`

**Total borrowed** ≈ `initial × ratio × (1 − ratioⁿ) / (1 − ratio)`

Example: initial=1000 USDT, ratio=0.8, loops=5 → ~2689 USDT total borrowed.

Tasks run as FastAPI background tasks and are stored in-memory (`TASKS` dict). Each task has a log and a `stop` flag that halts the loop at the next iteration boundary.

---

## Key Files

### `main.py`

- `make_exchange(eid)` — Instantiates a ccxt exchange with stored credentials
- `_do_borrow()` / `_do_repay()` — Unified borrow/repay with exchange-specific fallbacks
- `_run_loop()` — Async background function for loop borrowing
- All routes are grouped by feature: exchanges → balances → orders → withdraw → borrow → loop

### `static/index.html`

Single-file SPA. JavaScript is embedded at the bottom. Key sections:

- `S` — global state (`exchange`, etc.)
- `api(method, path, body)` — generic fetch wrapper with error toasts
- `toast(msg, type)` — Bootstrap toast notifications
- `startPoll()` / `loadTasks()` — 2-second polling for running loop tasks
- Each tab has corresponding `submit*()` and `load*()` functions

---

## Security Notes

- **API keys** are stored in `config.json` on disk, which is gitignored
- This tool is designed to run **locally** — do not expose it to the public internet without authentication
- All financial operations require a browser `confirm()` dialog before execution
- Withdrawal confirmation shows the full address; double-check before confirming

---

## Git Conventions

### Branch Naming
- Features: `feature/<short-description>`
- Bug fixes: `fix/<short-description>`
- Claude-initiated: `claude/<description>-<session-id>`

### Commit Messages
Imperative mood, subject ≤ 72 chars:

```
Add batch repay endpoint
Fix OKX passphrase not passed to ccxt
Support Bybit isolated margin borrowing
```

---

## For AI Assistants

### Before modifying
- Read `main.py` and `static/index.html` before proposing changes
- The frontend communicates with the backend exclusively via `fetch()` calls to `/api/*`
- Exchange-specific API paths live in `_do_borrow()` and `_do_repay()` — add new exchanges there

### Adding a new exchange
1. Add the exchange ID to `SUPPORTED` in `main.py`
2. Add fallback branches in `_do_borrow()` and `_do_repay()` for non-unified ccxt methods
3. Add the `<option>` to `#newExchangeSel` in `index.html`

### Adding a new feature
1. Add a Pydantic model for the request body in `main.py`
2. Add the FastAPI route
3. Add a tab/form in `index.html` with the corresponding JS function
4. Update the API table in this file

### What NOT to do
- Do not commit `config.json`
- Do not add authentication — this is a local tool
- Do not add a database — in-memory task storage is intentional for simplicity
- Do not introduce a JS build step — the frontend is intentionally dependency-free

---

## Potential Future Additions

- Transfer between spot and margin accounts (endpoint exists, UI not yet added)
- Loop repay (reverse loop borrow to unwind positions)
- Order history and PnL tracking
- Multi-exchange portfolio overview on dashboard
- Persistent task storage (SQLite)

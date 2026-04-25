# portfolio-mcp

An MCP (Model Context Protocol) server that connects Claude to your Upstox portfolio. Claude calls the tools to fetch your holdings and fundamental data — it does all the analysis and reasoning itself.

---

## How it works

```
Claude Desktop / Claude.ai
        |
        | MCP (stdio)
        v
  portfolio-mcp server
        |
        |-- Upstox SDK       → your live holdings
        |-- Screener.in      → fundamentals (PE, ROE, debt/equity, etc.)
        |-- Tickertape API   → fallback if Screener data is incomplete
        `-- NSE India API    → corporate actions, exchange filings
```

Claude calls a tool, gets back JSON, and reasons over it. No separate AI calls are made server-side.

---

## Setup

### 1. Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) — `pip install uv`
- An Upstox developer account and a daily access token

### 2. Clone and install

```bash
git clone <repo>
cd portfolio-mcp
uv sync
```

### 3. Configure `.env`

```env
APP_ENV=development
SECRET_KEY=change-me-to-a-long-random-string

# Get your daily access token from https://developer.upstox.com/
UPSTOX_ACCESS_TOKEN=<your_token>

DB_PATH=portfolio_mcp.db
```

> Upstox access tokens expire at the end of each trading day. Update `UPSTOX_ACCESS_TOKEN` in `.env` each morning.

---

## Running

### As an MCP server (Claude Desktop)

Add this to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on Mac):

```json
{
  "mcpServers": {
    "portfolio-mcp": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/portfolio-mcp", "python", "-m", "portfolio_mcp"]
    }
  }
}
```

Or run it directly for testing:

```bash
uv run python -m portfolio_mcp
```

---

## Tools exposed to Claude

| Tool | What it does |
|------|-------------|
| `get_holdings` | Fetches your live holdings from Upstox — ticker, quantity, average cost, current price, P&L |
| `get_enriched_holdings` | Same as above, plus fundamental data from Screener.in for each holding (PE, PB, ROE, ROCE, debt/equity, promoter holding, revenue/earnings growth) |
| `get_user_profile` | Retrieves your saved investment profile (risk tolerance, goals, horizon) |
| `upsert_user_profile` | Creates or updates your investment profile so Claude can personalise its analysis |

---

## File structure

```
portfolio-mcp/
├── .env                        # secrets — UPSTOX_ACCESS_TOKEN goes here
├── pyproject.toml              # dependencies and project metadata
└── src/portfolio_mcp/
    ├── __main__.py             # entry point — runs mcp.run() (stdio transport)
    ├── server.py               # FastMCP server, all tool definitions
    ├── config.py               # settings loaded from .env via pydantic-settings
    ├── schemas.py              # shared data models (Holding, Portfolio, FundamentalData, etc.)
    │
    ├── brokers/
    │   ├── upstox.py           # Upstox SDK adapter — fetches holdings, normalises to shared schema
    │   └── router.py           # returns the UpstoxAdapter singleton
    │
    └── data/
    │   ├── pipeline.py         # orchestrates enrichment — runs NSE/BSE + Screener in parallel,
    │   │                       #   falls back to Tickertape if Screener data is incomplete
    │   ├── screener.py         # scrapes Screener.in for fundamentals (primary source)
    │   ├── tickertape.py       # calls Tickertape's internal API (fallback source)
    │   └── nse_bse.py          # hits NSE India's JSON endpoints for corporate actions + filings
    │
    ├── profile/
    │   └── store.py            # SQLite-backed store for user investment profiles
    │
    └── assessment/
        └── __init__.py         # (empty — assessment is done by Claude, not server-side)
```

---

## How the files connect

```
server.py
  └── get_holdings()
        └── brokers/router.py → brokers/upstox.py
              └── upstox_client SDK (UPSTOX_ACCESS_TOKEN from config.py)
                    → returns Portfolio (schemas.py)

  └── get_enriched_holdings()
        ├── brokers/router.py → brokers/upstox.py   (same as above)
        └── data/pipeline.py
              ├── data/nse_bse.py     → NSE India API (corporate actions, filings)
              ├── data/screener.py    → Screener.in HTML scraper (primary fundamentals)
              └── data/tickertape.py  → Tickertape internal API (fallback fundamentals)
                    → merges into FundamentalData (schemas.py), attached to each Holding

  └── get_user_profile() / upsert_user_profile()
        └── profile/store.py  → SQLite (DB_PATH from config.py)
```

### Data enrichment flow (`pipeline.py`)

For each holding, `pipeline.py` runs three fetches in parallel:
1. **NSE/BSE** — corporate actions (dividends, splits, buybacks) and recent exchange filings
2. **Screener.in** — key ratios via HTML scraping (PE, PB, ROCE, promoter holding, etc.)
3. If Screener is missing PE, debt/equity, or promoter holding → **Tickertape** fills the gaps

All results merge into a single `FundamentalData` object attached to the holding.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `upstox-python-sdk` | Official Upstox v2 SDK for fetching holdings |
| `httpx` | Async HTTP client for Screener, Tickertape, NSE scraping |
| `mcp` | MCP server framework (FastMCP) |
| `pydantic` / `pydantic-settings` | Data models and `.env` loading |
| `cryptography` | Token encryption at rest (profile store) |
| `uvicorn` | ASGI server (optional, for HTTP transport) |

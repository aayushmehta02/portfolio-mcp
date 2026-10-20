# portfolio-mcp

An MCP (Model Context Protocol) server that lets Claude read your Indian brokerage portfolio and the fundamentals behind each holding. The server supplies the data; Claude does the analysis. No LLM calls happen inside the server.

**Supported brokers:** Upstox, Fyers, Angel One, Dhan, ICICI Direct.

## What it does

- Connects to each broker through its own login flow, with one `connect_*` tool per broker.
- Merges holdings across whichever brokers you mark active into a single portfolio.
- Enriches each holding with fundamentals from Screener.in (cached in SQLite for 6 hours) and corporate actions from NSE.
- Returns the whole portfolio as one dataset (`assess_portfolio`): weights, P&L, concentration, per-holding fundamentals and simple red-flag pre-checks, ready for Claude to reason over.

## How it works

```
Claude Desktop / Claude.ai
        |
        | MCP (stdio)
        v
  portfolio-mcp server (FastMCP)
        |
        |-- brokers/   one adapter per broker, normalised to a shared Holding schema
        |-- auth/      per-broker login flows + a temporary local callback server
        |-- data/      Screener.in (primary), Tickertape (best-effort fallback), NSE (corporate actions)
        `-- profile/   SQLite store for your investor profile
```

## Setup

**Prerequisites:** Python 3.10+, [uv](https://github.com/astral-sh/uv), and API credentials for the broker(s) you want to use.

```bash
git clone https://github.com/aayushmehta02/portfolio-mcp
cd portfolio-mcp
uv sync
```

Create a `.env` in the project root with the credentials for your brokers (only the ones you use):

| Broker | Variables |
|--------|-----------|
| Upstox | `UPSTOX_API_KEY`, `UPSTOX_API_SECRET` |
| Fyers | `FYERS_APP_ID`, `FYERS_SECRET_KEY` |
| Angel One | `ANGEL_API_KEY` |
| Dhan | `DHAN_CLIENT_ID`, `DHAN_APP_ID`, `DHAN_APP_SECRET` |
| ICICI Direct | `ICICI_API_KEY`, `ICICI_API_SECRET` |

Optional: `ACTIVE_BROKERS` (comma-separated), `DB_PATH` (default `portfolio_mcp.db`), `SECRET_KEY`.

Access tokens are not set by hand. The `connect_*` tools write them into `.env` after you log in, so keep that file private (it is git-ignored).

### Add it to Claude Desktop

```bash
python setup_claude_desktop.py
```

This adds a `portfolio-mcp` entry to Claude Desktop's config, pointing at the project's `.venv`. Restart Claude Desktop afterwards. To run the server directly instead:

```bash
uv run python -m portfolio_mcp
```

### Connect a broker

Ask Claude to connect the broker, for example "connect my Upstox account". Claude calls `connect_upstox`, which opens the broker's login page in your browser. A temporary local server on port 8888 captures the authorisation code (Upstox redirects through the small hosted page in `vercel/`) and the token is saved automatically. Repeat whenever a session expires.

## Tools

| Tool | What it does |
|------|--------------|
| `broker_status` | Shows which brokers are configured, connected and active |
| `set_active_brokers` | Chooses which brokers contribute to the portfolio |
| `connect_upstox` / `connect_fyers` / `connect_angel_one` / `connect_dhan` / `connect_icici_direct` | Log in to a broker and save its access token |
| `get_holdings` | Live holdings merged across active brokers: ticker, quantity, average cost, current price, P&L |
| `get_enriched_holdings` | Holdings plus fundamentals for each (PE, PB, ROE, ROCE, debt/equity, promoter holding, growth) |
| `get_stock_fundamentals` | Deep fundamentals for a single NSE ticker: ratios, 5-year P&L, last 6 quarters |
| `assess_portfolio` | The full enriched dataset for portfolio assessment, with concentration metrics and red-flag pre-checks |
| `get_user_profile` / `upsert_user_profile` | Read or save an investor profile (risk tolerance, goals, horizon) |

## Data sources

- **Screener.in** is the primary source for fundamentals, parsed from server-rendered HTML.
- **Tickertape** is a best-effort fallback when Screener data is incomplete.
- **NSE India** unofficial JSON endpoints provide corporate actions and filings. NSE may rate-limit or block these requests.

These are unofficial endpoints and page layouts can change, so scraper breakage is the most likely failure mode.

## Project layout

```
src/portfolio_mcp/
├── server.py          # FastMCP server and all tool definitions
├── config.py          # settings from .env; helper that writes tokens back to .env
├── schemas.py         # shared models (Holding, Portfolio, FundamentalData, UserProfile, ...)
├── brokers/           # adapter interface, router, and one adapter per broker
├── auth/              # per-broker login flows and the local callback server
├── data/              # screener, tickertape, nse_bse, SQLite cache, enrichment pipeline
└── profile/           # SQLite-backed investor profile store
vercel/                # hosted OAuth callback and "connected" pages
tests/                 # unit tests
```

## Development

```bash
uv run pytest
```

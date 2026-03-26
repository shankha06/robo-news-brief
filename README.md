# The Brief

A personal intelligence dashboard that aggregates news, football, AI/ML research, and market data into a single clean interface — so you never have to scroll through ten different sites every morning.

![Python](https://img.shields.io/badge/python-3.10+-blue) ![Flask](https://img.shields.io/badge/flask-3.x-lightgrey) ![License](https://img.shields.io/badge/license-MIT-green)

## What it does

**Top Stories** — Curated from NDTV, Times of India, Economic Times, Livemint, Moneycontrol, BBC, TechCrunch, and Google News. Articles are scored by relevance (India-first, finance, tech, geopolitics) and tagged by category. Filter by Finance, Tech, Politics, or Jobs.

**Football** — Latest news from BBC Sport, ESPN FC, and Google News football feeds.

**AI/ML Research** — Papers and blog posts from arXiv (CS.CL, CS.AI, CS.LG, CS.IR), OpenAI, Anthropic, Google AI, HuggingFace, The Gradient, and Lil'Log. Scored by topic relevance — LLMs, RL, retrieval, ranking, agents all rank higher. Filter by LLM, RL, Agents, or RAG.

**Market Ticker** — Scrolling strip with NIFTY 50, SENSEX, BANK NIFTY, NIFTY IT, S&P 500, NASDAQ, DOW JONES, Gold, Crude Oil, and USD/INR via Yahoo Finance.

**Match Scores** — Bottom banner with results from the last 7 days across Premier League, Champions League, La Liga, Bundesliga, Serie A, Ligue 1, Europa League, and Conference League. Filtered to only show matches involving top-performing teams. Data from ESPN.

**Search** — Google search bar that opens results in a new browser tab.

## Quick start

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python 3.10+.

```bash
# Clone and enter the directory
cd /path/to/daily_chore

# Install dependencies and run
uv run python app.py
```

Open **http://localhost:5566** in your browser.

That's it. `uv` handles the virtual environment and dependency installation automatically on first run.

## Manual setup (without uv)

```bash
python -m venv .venv
source .venv/bin/activate
pip install flask feedparser requests yfinance
python app.py
```

## Configuration

All configuration lives at the top of `app.py`:

- `RSS_FEEDS` — add/remove news sources per category
- `STOCK_SYMBOLS` — edit tickers shown in the market strip
- `FOOTBALL_LEAGUES` — which leagues to pull scores from
- `TOP_TEAMS` — which clubs count as "top-performing" per league
- `HIGH_PRIORITY_KEYWORDS` — keywords that boost article ranking
- `AI_PRIORITY_KEYWORDS` — keywords that boost AI research ranking
- `CACHE_TTL` — how long data is cached (default 5 minutes, scores 10 minutes)

## Tech stack

- **Backend**: Python, Flask, feedparser, yfinance, requests
- **Frontend**: Vanilla HTML/CSS/JS — no build step, no framework
- **Fonts**: SF Pro (system), Newsreader (serif headlines), JetBrains Mono (tickers)
- **APIs**: RSS feeds, Yahoo Finance, ESPN scoreboard (all free, no keys needed)

## Project structure

```
daily_chore/
  app.py                 # Flask server + all backend logic
  templates/
    index.html           # Single-page dashboard
  static/
    css/style.css        # All styles
    js/app.js            # All frontend logic
  requirements.txt
  pyproject.toml
```

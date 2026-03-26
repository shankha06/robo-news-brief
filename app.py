#!/usr/bin/env python3
"""Daily Chore Dashboard - Personal news, stocks & search aggregator."""

import os
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import feedparser
import requests
import yfinance as yf
from flask import Flask, jsonify, render_template, request
from newspaper import Article
from googlenewsdecoder import new_decoderv1

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RSS_FEEDS = {
    "top_news": [
        # India national news
        ("NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories"),
        ("Times of India", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
        ("Economic Times", "https://economictimes.indiatimes.com/rssfeedstopstories.cms"),
        ("Livemint", "https://www.livemint.com/rss/news"),
        ("Moneycontrol", "https://www.moneycontrol.com/rss/latestnews.xml"),
        # High-quality global news
        ("BBC News", "https://feeds.bbci.co.uk/news/rss.xml"),
        ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
        ("Google News", "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"),
        ("Google News India", "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"),
        # Tech & Jobs
        ("TechCrunch", "https://techcrunch.com/feed/"),
        ("Google Tech", "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en"),
        ("Google Jobs/Layoffs", "https://news.google.com/rss/search?q=job+cuts+OR+layoffs+OR+WFH+OR+remote+work&hl=en-US&gl=US&ceid=US:en"),
    ],
    "football": [
        ("BBC Football", "https://feeds.bbci.co.uk/sport/football/rss.xml"),
        ("ESPN Soccer", "https://www.espn.com/espn/rss/soccer/news"),
        ("Google Football", "https://news.google.com/rss/search?q=football+soccer+Premier+League+OR+Champions+League+OR+La+Liga+OR+ISL+India&hl=en-IN&gl=IN&ceid=IN:en"),
        ("Google Transfer News", "https://news.google.com/rss/search?q=football+transfer+news+2026&hl=en-IN&gl=IN&ceid=IN:en"),
    ],
    "ai_research": [
        # arXiv feeds — LLM, RL, retrieval, ranking, agents
        ("arXiv CS.CL", "https://rss.arxiv.org/rss/cs.CL"),
        ("arXiv CS.AI", "https://rss.arxiv.org/rss/cs.AI"),
        ("arXiv CS.LG", "https://rss.arxiv.org/rss/cs.LG"),
        ("arXiv CS.IR", "https://rss.arxiv.org/rss/cs.IR"),
        # Top AI blogs
        ("Google AI", "https://blog.research.google/feeds/posts/default?alt=rss"),
        ("OpenAI", "https://openai.com/blog/rss.xml"),
        ("Anthropic", "https://www.anthropic.com/rss/research.rss"),
        ("HuggingFace", "https://huggingface.co/blog/feed.xml"),
        ("The Gradient", "https://thegradient.pub/rss/"),
        ("Lil'Log", "https://lilianweng.github.io/index.xml"),
        # Aggregated AI news
        ("Google AI News", "https://news.google.com/rss/search?q=LLM+OR+large+language+model+OR+reinforcement+learning+OR+AI+agents+OR+RAG+retrieval&hl=en-US&gl=US&ceid=US:en"),
    ],
}

# Prioritised tickers: key indices + commodities only
STOCK_SYMBOLS = {
    "india": [
        ("NIFTY 50", "^NSEI"),
        ("SENSEX", "^BSESN"),
        ("BANK NIFTY", "^NSEBANK"),
        ("NIFTY IT", "^CNXIT"),
    ],
    "us": [
        ("S&P 500", "^GSPC"),
        ("NASDAQ", "^IXIC"),
        ("DOW JONES", "^DJI"),
    ],
    "commodities": [
        ("GOLD", "GC=F"),
        ("CRUDE OIL", "CL=F"),
        ("USD/INR", "INR=X"),
    ],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}

# Simple in-memory cache
_cache: dict = {}
CACHE_TTL = 300  # 5 minutes


def _cached(key: str, ttl: int = CACHE_TTL):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < ttl:
        return entry["data"]
    return None


def _set_cache(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}


# ---------------------------------------------------------------------------
# News relevance scoring
# ---------------------------------------------------------------------------

HIGH_PRIORITY_KEYWORDS = [
    # India-critical
    "india", "modi", "rbi", "sensex", "nifty", "rupee", "parliament", "lok sabha",
    "rajya sabha", "supreme court", "delhi", "mumbai", "bengaluru", "bangalore",
    "hyderabad", "chennai", "kolkata", "pune", "budget", "gdp", "inflation",
    "isro", "upi", "aadhaar", "gst",
    # Finance
    "market crash", "rally", "interest rate", "fed", "recession", "ipo",
    "stock market", "bull", "bear", "sebi",
    # Tech & Jobs
    "layoff", "job cut", "hiring freeze", "wfh", "remote work", "ai",
    "startup", "unicorn", "funding",
    # Geopolitics that affects India
    "tariff", "trade war", "china", "pakistan", "us-india", "sanctions",
    "opec", "oil price", "climate", "g20", "brics",
    # Big impact
    "breaking", "exclusive", "major", "crisis", "emergency", "war",
    "election", "resignation", "arrested",
]

# AI/ML keywords for scoring research articles
AI_PRIORITY_KEYWORDS = [
    "llm", "large language model", "gpt", "transformer", "attention",
    "reinforcement learning", "rlhf", "rl", "ppo", "reward model",
    "retrieval", "rag", "dense retrieval", "vector search", "embedding",
    "ranking", "learning to rank", "recommendation", "reranking",
    "agent", "tool use", "function calling", "multi-agent", "agentic",
    "fine-tuning", "lora", "qlora", "instruction tuning",
    "reasoning", "chain of thought", "cot", "tree of thought",
    "diffusion", "multimodal", "vision language", "mllm",
    "benchmark", "evaluation", "scaling law",
    "claude", "gemini", "llama", "mistral", "openai", "anthropic", "deepmind",
]

CATEGORY_TAGS = {
    "Finance": ["market crash", "stock market", "sensex", "nifty", "bank nifty",
                 "rbi", "investment", "economy", "gdp", "inflation", "rupee",
                 "ipo", "sebi", "revenue", "profit", "crypto", "bitcoin",
                 "budget", "fiscal", "forex", "trading", "bull market",
                 "bear market", "mutual fund", "interest rate", "bond",
                 "dow jones", "nasdaq", "s&p 500", "wall street", "fed rate",
                 "earnings", "quarterly result", "share price", "commodity",
                 "gold price", "crude oil", "banking", "fintech"],
    "AI": ["artificial intelligence", "chatgpt", "openai", "claude", "anthropic",
            "gemini", "llm", "large language model", "generative ai", "gen ai",
            "deepfake", "machine learning", "neural network", "ai model",
            "ai regulation", "ai safety", "ai startup", "copilot", "midjourney",
            "stable diffusion", "ai chip", "nvidia ai", "google ai", "meta ai",
            "ai agent", "gpt-4", "gpt-5", "ai tool", "deepseek", "mistral",
            "hugging face", "transformer", "ai investment", "ai company"],
    "Tech": ["startup", "apple", "microsoft", "amazon", "meta", "nvidia",
             "software", "cyber", "digital", "5g", "semiconductor", "chip",
             "isro", "space", "elon musk", "tesla", "spacex", "iphone",
             "android", "cloud computing", "saas", "data breach", "hack",
             "smartphone", "laptop", "gadget", "internet", "broadband",
             "telecom", "jio", "airtel", "samsung", "quantum computing",
             "blockchain", "web3", "robotics", "drone", "ev", "electric vehicle"],
    "Jobs": ["layoff", "job cut", "hiring freeze", "wfh", "remote work", "fired",
             "retrench", "workforce reduction", "unemployment", "recruiting",
             "mass layoff", "job loss", "downsizing", "pink slip", "severance",
             "return to office", "rto", "gig economy", "freelance",
             "hiring spree", "job market", "talent crunch", "h-1b", "visa"],
    "World": ["war", "nato", "united nations", "summit", "diplomat", "sanction",
              "treaty", "nuclear", "military", "conflict", "refugee", "g20",
              "brics", "ceasefire", "invasion", "missile", "drone strike",
              "peace talk", "humanitarian", "genocide", "coup", "uprising",
              "territorial", "south china sea", "taiwan strait", "korean peninsula"],
    "Politics": ["modi", "parliament", "election", "congress party", "bjp",
                 "aap", "lok sabha", "rajya sabha", "supreme court", "governor",
                 "trump", "biden", "minister", "policy", "legislation", "bill passed",
                 "opposition", "ruling party", "chief minister", "prime minister",
                 "president", "amendment", "constitution", "vote", "ballot",
                 "campaign", "political party", "rahul gandhi", "amit shah",
                 "home minister", "finance minister"],
    "Sports": ["cricket", "ipl", "football", "tennis", "olympics", "fifa",
               "match", "tournament", "champion", "medal", "world cup",
               "premier league", "champions league", "la liga", "serie a",
               "bundesliga", "t20", "odi", "test match", "virat kohli",
               "rohit sharma", "f1", "formula 1", "grand prix", "athletics"],
}

AI_CATEGORY_TAGS = {
    "LLM": ["llm", "large language model", "gpt", "transformer", "attention",
             "fine-tuning", "lora", "instruction tuning", "pretraining",
             "tokenizer", "scaling", "claude", "gemini", "llama", "mistral"],
    "RL": ["reinforcement learning", "rlhf", "reward model", "ppo", "dpo",
            "policy gradient", "q-learning", "rl from", "grpo"],
    "Retrieval": ["retrieval", "rag", "dense retrieval", "vector", "embedding",
                   "search", "reranking", "rerank", "colbert", "bi-encoder"],
    "Ranking": ["ranking", "learning to rank", "recommendation", "collaborative filtering",
                 "click model", "ndcg", "relevance"],
    "Agents": ["agent", "tool use", "function calling", "multi-agent", "agentic",
                "planning", "web agent", "code agent", "mcp", "a2a"],
    "Reasoning": ["reasoning", "chain of thought", "cot", "tree of thought",
                   "step-by-step", "math", "logic", "benchmark"],
    "Vision": ["multimodal", "vision language", "image", "video", "diffusion",
                "text-to-image", "mllm", "visual"],
}


def _score_article(item: dict) -> float:
    """Score an article by relevance. Higher = more important."""
    text = (item.get("title", "") + " " + item.get("description", "")).lower()
    score = 0.0

    for kw in HIGH_PRIORITY_KEYWORDS:
        if kw in text:
            score += 2.0

    # Boost recent articles
    pub = item.get("published", "")
    if pub:
        try:
            age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(pub)).total_seconds() / 3600
            if age_hours < 3:
                score += 5.0
            elif age_hours < 6:
                score += 3.0
            elif age_hours < 12:
                score += 1.5
            elif age_hours < 24:
                score += 0.5
        except Exception:
            pass

    # Deprioritize hyperlocal foreign news
    local_foreign = [
        "county", "sheriff", "township", "borough", "precinct", "school board",
        "state trooper", "local police", "neighborhood",
    ]
    if any(lf in text for lf in local_foreign):
        if "india" not in text:
            score -= 8.0

    return score


def _score_ai_article(item: dict) -> float:
    """Score an AI research article. Higher = more relevant."""
    text = (item.get("title", "") + " " + item.get("description", "")).lower()
    score = 0.0

    for kw in AI_PRIORITY_KEYWORDS:
        if kw in text:
            score += 3.0

    # Boost recent
    pub = item.get("published", "")
    if pub:
        try:
            age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(pub)).total_seconds() / 3600
            if age_hours < 24:
                score += 4.0
            elif age_hours < 72:
                score += 2.0
            elif age_hours < 168:
                score += 1.0
        except Exception:
            pass

    # Boost blog posts from top labs
    source = item.get("source", "").lower()
    top_sources = ["openai", "anthropic", "google ai", "huggingface", "deepmind", "lil'log", "the gradient"]
    if any(s in source for s in top_sources):
        score += 5.0

    return score


def _tag_article(item: dict) -> str:
    """Assign a category tag to a news article using weighted keyword scoring."""
    title = item.get("title", "").lower()
    desc = item.get("description", "").lower()
    text = title + " " + desc
    best_tag = ""
    best_score = 0.0
    for tag, keywords in CATEGORY_TAGS.items():
        score = 0.0
        for kw in keywords:
            if kw in text:
                # Multi-word keywords are more specific → higher weight
                weight = len(kw.split())
                # Title matches are worth 3x description matches
                if kw in title:
                    score += weight * 3.0
                else:
                    score += weight * 1.0
        if score > best_score:
            best_score = score
            best_tag = tag
    return best_tag or "General"


def _tag_ai_article(item: dict) -> str:
    """Assign a category tag to an AI article."""
    text = (item.get("title", "") + " " + item.get("description", "")).lower()
    best_tag = ""
    best_count = 0
    for tag, keywords in AI_CATEGORY_TAGS.items():
        count = sum(1 for kw in keywords if kw in text)
        if count > best_count:
            best_count = count
            best_tag = tag
    return best_tag or "ML"


# ---------------------------------------------------------------------------
# Google News URL resolver
# ---------------------------------------------------------------------------

def _resolve_google_news_url(gn_url: str) -> str:
    """Decode a Google News redirect URL to the actual article URL."""
    try:
        result = new_decoderv1(gn_url, interval=None)
        if result.get("status") and result.get("decoded_url"):
            return result["decoded_url"]
    except Exception:
        pass
    return gn_url


# ---------------------------------------------------------------------------
# Feed helpers
# ---------------------------------------------------------------------------

def _fetch_feed(source_name: str, url: str) -> list[dict]:
    """Parse one RSS feed and return normalised items."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        feed = feedparser.parse(resp.content)
    except Exception:
        return []

    items = []
    for entry in feed.entries[:15]:
        # Extract thumbnail
        thumb = ""
        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            thumb = entry.media_thumbnail[0].get("url", "")
        elif hasattr(entry, "media_content") and entry.media_content:
            for mc in entry.media_content:
                if "image" in mc.get("type", "") or mc.get("url", "").endswith(
                    (".jpg", ".png", ".webp")
                ):
                    thumb = mc["url"]
                    break
        if not thumb and hasattr(entry, "links"):
            for link in entry.links:
                if "image" in link.get("type", ""):
                    thumb = link.get("href", "")
                    break
        if not thumb and hasattr(entry, "enclosures"):
            for enc in entry.enclosures:
                if "image" in enc.get("type", ""):
                    thumb = enc.get("href", "")
                    break

        # Parse date
        published = ""
        dt = entry.get("published_parsed") or entry.get("updated_parsed")
        if dt:
            try:
                published = datetime(*dt[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass

        # Clean description (strip HTML)
        desc = entry.get("summary", "") or entry.get("description", "")
        desc = re.sub(r"<[^>]+>", "", desc).strip()
        if len(desc) > 220:
            desc = desc[:217] + "..."

        link = entry.get("link", "")
        # Resolve Google News redirect URLs to actual article URLs
        if "news.google.com" in link:
            link = _resolve_google_news_url(link)

        items.append({
            "title": entry.get("title", ""),
            "link": link,
            "source": source_name,
            "published": published,
            "description": desc,
            "thumbnail": thumb,
        })
    return items


def _fetch_all_feeds(category: str) -> list[dict]:
    """Fetch all feeds for a category in parallel, score and rank."""
    cached = _cached(f"feeds_{category}")
    if cached is not None:
        return cached

    feeds = RSS_FEEDS.get(category, [])
    all_items: list[dict] = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_feed, name, url): name for name, url in feeds}
        for future in as_completed(futures):
            try:
                all_items.extend(future.result())
            except Exception:
                pass

    # Deduplicate by title similarity
    seen_titles: set[str] = set()
    unique: list[dict] = []
    is_ai = category == "ai_research"
    for item in all_items:
        key = re.sub(r"\W+", "", item["title"].lower())[:50]
        if key not in seen_titles:
            seen_titles.add(key)
            if is_ai:
                item["tag"] = _tag_ai_article(item)
                item["score"] = _score_ai_article(item)
            else:
                item["tag"] = _tag_article(item)
                item["score"] = _score_article(item)
            unique.append(item)

    # Sort by score (highest first), then by date
    unique.sort(key=lambda x: (x.get("score", 0), x.get("published", "")), reverse=True)
    limit = 50
    result = unique[:limit]
    _set_cache(f"feeds_{category}", result)
    return result


# ---------------------------------------------------------------------------
# Stock helpers
# ---------------------------------------------------------------------------

def _fetch_stocks(market: str) -> list[dict]:
    """Fetch all stocks for a market using yfinance."""
    cached = _cached(f"stocks_{market}")
    if cached is not None:
        return cached

    symbols = STOCK_SYMBOLS.get(market, [])
    label_map = {sym: label for label, sym in symbols}
    sym_list = [sym for _, sym in symbols]

    results: list[dict] = []
    try:
        tickers = yf.Tickers(" ".join(sym_list))
        for sym in sym_list:
            try:
                info = tickers.tickers[sym].fast_info
                price = float(info.last_price)
                prev_close = float(info.previous_close)
                change = price - prev_close
                change_pct = (change / prev_close * 100) if prev_close else 0
                currency = getattr(info, "currency", "USD") or "USD"

                results.append({
                    "label": label_map[sym],
                    "symbol": sym,
                    "price": round(price, 2),
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2),
                    "currency": currency,
                })
            except Exception as e:
                print(f"  Stock error {sym}: {e}")
    except Exception as e:
        print(f"  Batch stock fetch error: {e}")
        traceback.print_exc()

    order = {label: i for i, (label, _) in enumerate(symbols)}
    results.sort(key=lambda x: order.get(x["label"], 99))
    _set_cache(f"stocks_{market}", results)
    return results


# ---------------------------------------------------------------------------
# Football scores helpers
# ---------------------------------------------------------------------------

# Priority order: top European club leagues first, then UEFA, then internationals
FOOTBALL_LEAGUES = [
    ("eng.1", "Premier League", "PL"),
    ("uefa.champions", "Champions League", "UCL"),
    ("esp.1", "La Liga", "LaLiga"),
    ("ger.1", "Bundesliga", "BL"),
    ("ita.1", "Serie A", "SA"),
    ("fra.1", "Ligue 1", "L1"),
    ("uefa.europa", "Europa League", "UEL"),
    ("uefa.europa.conf", "Conference League", "UECL"),
    # Fallback international
    ("fifa.friendly", "International", "INTL"),
    ("uefa.nations", "Nations League", "UNL"),
]

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"

# Top-performing / marquee teams per league — only show matches involving these
TOP_TEAMS = {
    # Premier League — top 8ish
    "PL": {"arsenal", "man city", "liverpool", "chelsea", "man united",
            "newcastle", "tottenham", "aston villa", "brighton", "nottm forest"},
    # Champions League / Europa — all matches matter
    "UCL": None,  # None = show all
    "UEL": None,
    "UECL": None,
    # La Liga
    "LaLiga": {"real madrid", "barcelona", "atletico", "athletic", "villarreal",
               "real sociedad", "betis", "mallorca"},
    # Bundesliga
    "BL": {"bayern", "leverkusen", "dortmund", "stuttgart", "rb leipzig",
            "frankfurt", "freiburg"},
    # Serie A
    "SA": {"inter milan", "napoli", "atalanta", "juventus", "ac milan",
            "lazio", "roma", "fiorentina", "bologna"},
    # Ligue 1
    "L1": {"psg", "paris saint-germain", "marseille", "monaco", "lille", "lyon"},
    # Internationals — top nations
    "INTL": {"brazil", "argentina", "france", "england", "germany", "spain",
              "portugal", "india", "italy", "netherlands", "belgium"},
    "UNL": {"brazil", "argentina", "france", "england", "germany", "spain",
             "portugal", "india", "italy", "netherlands", "belgium"},
}


def _fetch_league_scores(league_code: str, league_name: str, short: str,
                         date_range: str) -> list[dict]:
    """Fetch finished match scores for one league from ESPN."""
    url = f"{ESPN_SCOREBOARD_URL.format(league=league_code)}?dates={date_range}&limit=50"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        data = resp.json()
    except Exception:
        return []

    matches = []
    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        status_obj = comp.get("status", {}).get("type", {})
        state = status_obj.get("state", "")
        detail = status_obj.get("shortDetail", "")

        # Only show completed or in-progress matches
        if state not in ("post", "in"):
            continue

        teams = comp.get("competitors", [])
        if len(teams) < 2:
            continue

        # ESPN: competitors[0] is home, competitors[1] is away
        home = teams[0]
        away = teams[1]

        match_date = event.get("date", "")

        matches.append({
            "event_id": event.get("id", ""),
            "league_code": league_code,
            "home": home["team"].get("shortDisplayName", home["team"].get("displayName", "?")),
            "away": away["team"].get("shortDisplayName", away["team"].get("displayName", "?")),
            "home_score": home.get("score", "?"),
            "away_score": away.get("score", "?"),
            "home_logo": home["team"].get("logo", ""),
            "away_logo": away["team"].get("logo", ""),
            "league": league_name,
            "league_short": short,
            "status": "FT" if state == "post" else detail,
            "date": match_date,
        })

    return matches


def _fetch_all_scores() -> list[dict]:
    """Fetch scores from all leagues for the last 7 days."""
    cached = _cached("football_scores", ttl=600)  # 10 min cache
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    start = now - __import__("datetime").timedelta(days=7)
    date_range = f"{start.strftime('%Y%m%d')}-{now.strftime('%Y%m%d')}"

    all_matches: list[dict] = []
    club_match_count = 0

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {}
        for code, name, short in FOOTBALL_LEAGUES:
            futures[pool.submit(_fetch_league_scores, code, name, short, date_range)] = short

        for future in as_completed(futures):
            try:
                result = future.result()
                short = futures[future]
                # Track club matches vs internationals
                is_intl = short in ("INTL", "UNL")
                if not is_intl:
                    club_match_count += len(result)
                all_matches.extend(result)
            except Exception:
                pass

    # If we have enough club matches, drop internationals
    if club_match_count >= 8:
        all_matches = [m for m in all_matches if m["league_short"] not in ("INTL", "UNL")]

    # Filter to only matches involving top teams
    filtered = []
    for m in all_matches:
        top = TOP_TEAMS.get(m["league_short"])
        if top is None:
            # None means show all (e.g. UCL, UEL)
            filtered.append(m)
            continue
        home_lc = m["home"].lower()
        away_lc = m["away"].lower()
        if any(t in home_lc or home_lc in t for t in top) or \
           any(t in away_lc or away_lc in t for t in top):
            filtered.append(m)

    # Sort by date descending (most recent first)
    filtered.sort(key=lambda x: x.get("date", ""), reverse=True)
    _set_cache("football_scores", filtered)
    return filtered


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/news/<category>")
def api_news(category):
    if category not in RSS_FEEDS:
        return jsonify({"error": "Unknown category"}), 400
    return jsonify(_fetch_all_feeds(category))


@app.route("/api/stocks/<market>")
def api_stocks(market):
    if market not in STOCK_SYMBOLS:
        return jsonify({"error": "Unknown market"}), 400
    return jsonify(_fetch_stocks(market))


@app.route("/api/stocks/all")
def api_stocks_all():
    """Return all markets combined."""
    all_stocks = {}
    for market in STOCK_SYMBOLS:
        all_stocks[market] = _fetch_stocks(market)
    return jsonify(all_stocks)


@app.route("/api/scores")
def api_scores():
    return jsonify(_fetch_all_scores())


@app.route("/api/match/<league>/<event_id>")
def api_match(league, event_id):
    """Fetch detailed match stats from ESPN."""
    cache_key = f"match_{league}_{event_id}"
    cached = _cached(cache_key, ttl=600)
    if cached is not None:
        return jsonify(cached)

    summary_url = (
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/"
        f"{league}/summary?event={event_id}"
    )
    try:
        resp = requests.get(summary_url, headers=HEADERS, timeout=12)
        sdata = resp.json()
    except Exception:
        return jsonify({"error": "Failed to fetch match data"}), 502

    # Header / score
    header = sdata.get("header", {})
    comps = header.get("competitions", [{}])[0]
    competitors = comps.get("competitors", [])

    teams = []
    for c in competitors:
        t = c.get("team", {})
        logos = t.get("logos", [])
        teams.append({
            "name": t.get("displayName", "?"),
            "short": t.get("abbreviation", ""),
            "score": c.get("score", "?"),
            "logo": logos[0].get("href", "") if logos else "",
            "home_away": c.get("homeAway", ""),
        })

    # Boxscore stats (select key ones)
    STAT_KEYS = [
        "Possession", "SHOTS", "ON GOAL", "Corner Kicks", "Fouls",
        "Yellow Cards", "Red Cards", "Offsides", "Saves",
        "Pass Completion %", "Accurate Passes",
    ]
    team_stats = []
    for t in sdata.get("boxscore", {}).get("teams", []):
        stat_map = {s["label"]: s["displayValue"] for s in t.get("statistics", [])}
        team_stats.append({
            "name": t.get("team", {}).get("displayName", "?"),
            "stats": {k: stat_map.get(k, "-") for k in STAT_KEYS},
        })

    # Key events (goals, cards)
    key_events = []
    for ke in sdata.get("keyEvents", []):
        etype = ke.get("type", {}).get("text", "")
        if etype not in (
            "Goal", "Yellow Card", "Red Card", "Substitution",
            "Penalty - Scored", "Penalty - Missed", "Own Goal",
        ):
            continue
        athletes = ke.get("participants", [])
        athlete_name = ""
        if athletes:
            athlete_name = athletes[0].get("athlete", {}).get("displayName", "")
        key_events.append({
            "type": etype,
            "clock": ke.get("clock", {}).get("displayValue", ""),
            "team": ke.get("team", {}).get("displayName", ""),
            "player": athlete_name,
        })

    # Game info
    gi = sdata.get("gameInfo", {})
    venue = gi.get("venue", {})

    result = {
        "teams": teams,
        "stats": team_stats,
        "events": key_events,
        "venue": venue.get("fullName", ""),
        "attendance": gi.get("attendance", ""),
    }
    _set_cache(cache_key, result)
    return jsonify(result)


@app.route("/api/article")
def api_article():
    """Fetch and parse a full article from its URL."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "Missing url parameter"}), 400

    # Resolve Google News redirect URLs
    if "news.google.com" in url:
        url = _resolve_google_news_url(url)

    # Check cache
    cache_key = f"article_{url}"
    cached = _cached(cache_key, ttl=1800)  # 30 min cache
    if cached is not None:
        return jsonify(cached)

    # Special handling for arXiv — extract abstract from the abs page
    if "arxiv.org" in url:
        return _parse_arxiv_article(url, cache_key)

    try:
        article = Article(url, headers=HEADERS)
        article.download()
        article.parse()

        text = article.text or ""

        # If newspaper4k got too little text, try a fallback with requests + basic extraction
        if len(text.strip()) < 100:
            text = _fallback_extract(url) or text

        # Collect images: top_image first, then any others (deduplicated)
        images = []
        if article.top_image:
            images.append(article.top_image)
        for img in article.images:
            if img not in images:
                images.append(img)
            if len(images) >= 5:
                break

        result = {
            "title": article.title or "",
            "authors": article.authors or [],
            "publish_date": article.publish_date.isoformat() if article.publish_date else "",
            "top_image": article.top_image or "",
            "images": images,
            "text": text,
            "source_url": url,
        }
        _set_cache(cache_key, result)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Failed to parse article: {str(e)}"}), 502


def _parse_arxiv_article(url: str, cache_key: str):
    """Parse an arXiv paper page for its abstract and metadata."""
    # Ensure we're hitting the abstract page
    abs_url = re.sub(r"/pdf/", "/abs/", url).split(".pdf")[0]
    try:
        resp = requests.get(abs_url, headers=HEADERS, timeout=12)
        html = resp.text

        title = ""
        m = re.search(r'<meta name="citation_title"\s+content="([^"]+)"', html)
        if m:
            title = m.group(1)

        authors = []
        for m in re.finditer(r'<meta name="citation_author"\s+content="([^"]+)"', html):
            authors.append(m.group(1))

        abstract = ""
        m = re.search(
            r'<blockquote[^>]*class="abstract[^"]*"[^>]*>\s*(?:<span[^>]*>Abstract:</span>\s*)?(.*?)</blockquote>',
            html, re.DOTALL,
        )
        if m:
            abstract = re.sub(r"<[^>]+>", "", m.group(1)).strip()

        # Get submission date
        pub_date = ""
        m = re.search(r'<meta name="citation_date"\s+content="([^"]+)"', html)
        if m:
            pub_date = m.group(1)

        result = {
            "title": title,
            "authors": authors[:10],
            "publish_date": pub_date,
            "top_image": "",
            "images": [],
            "text": abstract,
            "source_url": abs_url,
        }
        _set_cache(cache_key, result)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"Failed to parse arXiv article: {str(e)}"}), 502


def _fallback_extract(url: str) -> str:
    """Fallback text extraction using requests + regex for stubborn sites."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        html = resp.text

        # Try to find <article> tag content
        m = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL)
        if not m:
            # Try main content area
            m = re.search(
                r'<div[^>]*(?:class|id)=["\'][^"\']*(?:article|story|content|post)[^"\']*["\'][^>]*>(.*?)</div>',
                html, re.DOTALL,
            )
        if m:
            content = m.group(1)
            # Extract text from <p> tags
            paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", content, re.DOTALL)
            text = "\n\n".join(
                re.sub(r"<[^>]+>", "", p).strip() for p in paragraphs if len(p.strip()) > 30
            )
            if len(text) > 100:
                return text
    except Exception:
        pass
    return ""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5566))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    print(f"\n  The Brief — Your Morning Intelligence")
    print(f"  Open http://localhost:{port} in your browser\n")
    app.run(host="0.0.0.0", port=port, debug=debug)

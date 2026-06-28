#!/usr/bin/env python3
"""The Brief — Personal news, stocks & search aggregator (FastAPI edition)."""

import asyncio
import ipaddress
import json
import math
import os
import re
import socket
import time
import traceback
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

# Use OS trust store (macOS Keychain / Linux ca-certificates) so corporate SSL
# proxy certificates are trusted without disabling verification entirely.
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass  # falls back to certifi — fine on Render/standard Linux

import feedparser
import httpx
import trafilatura
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

try:
    from googlenewsdecoder import new_decoderv1 as _gnd_decoder
except ImportError:
    _gnd_decoder = None

_PILImage = None   # lazy-loaded on first image proxy request
_io_mod    = None
_PIL_AVAILABLE = None  # None = not yet checked; True/False after first attempt

def _ensure_pil() -> bool:
    global _PILImage, _io_mod, _PIL_AVAILABLE
    if _PIL_AVAILABLE is not None:
        return _PIL_AVAILABLE
    try:
        from PIL import Image as _img
        import io as _io
        _PILImage = _img
        _io_mod   = _io
        _PIL_AVAILABLE = True
    except ImportError:
        _PIL_AVAILABLE = False
    return _PIL_AVAILABLE

# ---------------------------------------------------------------------------
# HTTP client (lifecycle managed by lifespan)
# ---------------------------------------------------------------------------

_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http_client
    _http_client = httpx.AsyncClient(
        headers=HEADERS,
        timeout=httpx.Timeout(connect=5.0, read=12.0, write=5.0, pool=5.0),
        limits=httpx.Limits(max_connections=60, max_keepalive_connections=20),
        follow_redirects=True,
    )
    yield
    await _http_client.aclose()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RSS_FEEDS = {
    "top_news": [
        ("NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories"),
        ("Times of India", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
        ("Economic Times", "https://economictimes.indiatimes.com/rssfeedstopstories.cms"),
        ("Livemint", "https://www.livemint.com/rss/news"),
        ("Moneycontrol", "https://www.moneycontrol.com/rss/latestnews.xml"),
        ("BBC News", "https://feeds.bbci.co.uk/news/rss.xml"),
        ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
        ("The Guardian", "https://www.theguardian.com/world/rss"),
        ("Google News", "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"),
        ("Google News India", "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"),
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
        ("arXiv CS.CL", "https://rss.arxiv.org/rss/cs.CL"),
        ("arXiv CS.AI", "https://rss.arxiv.org/rss/cs.AI"),
        ("arXiv CS.LG", "https://rss.arxiv.org/rss/cs.LG"),
        ("arXiv CS.IR", "https://rss.arxiv.org/rss/cs.IR"),
        ("arXiv CS.CV", "https://rss.arxiv.org/rss/cs.CV"),
        ("arXiv CS.RO", "https://rss.arxiv.org/rss/cs.RO"),
        ("arXiv CS.MA", "https://rss.arxiv.org/rss/cs.MA"),
        ("arXiv stat.ML", "https://rss.arxiv.org/rss/stat.ML"),
        ("OpenAI", "https://openai.com/blog/rss.xml"),
        ("Anthropic", "https://www.anthropic.com/rss/research.rss"),
        ("Google AI", "https://blog.research.google/feeds/posts/default?alt=rss"),
        ("DeepMind", "https://deepmind.google/blog/rss.xml"),
        ("Mistral", "https://mistral.ai/blog-rss.xml"),
        ("Nvidia AI", "https://blogs.nvidia.com/feed/"),
        ("Microsoft Research", "https://www.microsoft.com/en-us/research/blog/feed/"),
        ("Meta AI", "https://research.facebook.com/feed/"),
        ("Apple ML", "https://machinelearning.apple.com/rss.xml"),
        ("Amazon Science", "https://www.amazon.science/index.rss"),
        ("Together AI", "https://www.together.ai/blog/rss.xml"),
        ("Google Developers", "https://developers.googleblog.com/feeds/posts/default?alt=rss"),
        ("The Keyword Google", "https://blog.google/rss/"),
        ("HuggingFace", "https://huggingface.co/blog/feed.xml"),
        ("The Gradient", "https://thegradient.pub/rss/"),
        ("Lil'Log", "https://lilianweng.github.io/index.xml"),
        ("The Batch", "https://www.deeplearning.ai/the-batch/feed/"),
        ("Import AI", "https://importai.substack.com/feed"),
        ("Sebastian Raschka", "https://magazine.sebastianraschka.com/feed"),
        ("Simon Willison", "https://simonwillison.net/atom/everything/"),
        ("Chip Huyen", "https://huyenchip.com/feed.xml"),
        ("Jay Alammar", "https://jalammar.github.io/feed.xml"),
        ("r/MachineLearning", "https://www.reddit.com/r/MachineLearning/.rss"),
        ("r/LocalLLaMA", "https://www.reddit.com/r/LocalLLaMA/.rss"),
        ("HN AI", "https://hnrss.org/newest?q=LLM+OR+GPT+OR+transformer+OR+%22machine+learning%22"),
        ("NeurIPS Blog", "https://blog.neurips.cc/feed/"),
        ("AAAI", "https://aaai.org/feed/"),
        ("Google AI News", "https://news.google.com/rss/search?q=LLM+OR+large+language+model+OR+reinforcement+learning+OR+AI+agents+OR+RAG+retrieval&hl=en-US&gl=US&ceid=US:en"),
    ],
}

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
        ("BRENT CRUDE", "BZ=F"),
        ("USD/INR", "INR=X"),
    ],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
}

CACHE_TTL = 900  # seconds (15 min — feeds: top_news, football, ai_research, stocks)

# ---------------------------------------------------------------------------
# Simple in-memory cache
# ---------------------------------------------------------------------------

_cache: dict = {}


def _cached(key: str, ttl: int = CACHE_TTL):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < ttl:
        return entry["data"]
    return None


def _set_cache(key: str, data) -> None:
    _cache[key] = {"data": data, "ts": time.time()}


# ---------------------------------------------------------------------------
# Circuit breaker (per feed URL)
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """3 failures → open for 120s, then half-open."""

    _threshold = 3
    _recovery = 120.0

    def __init__(self):
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def is_open(self, key: str) -> bool:
        if self._failures.get(key, 0) < self._threshold:
            return False
        elapsed = time.monotonic() - self._opened_at.get(key, 0)
        if elapsed < self._recovery:
            return True
        # Half-open: reset to threshold-1 so one more failure re-opens
        self._failures[key] = self._threshold - 1
        return False

    def record_failure(self, key: str) -> None:
        self._failures[key] = self._failures.get(key, 0) + 1
        if self._failures[key] >= self._threshold:
            self._opened_at[key] = time.monotonic()

    def record_success(self, key: str) -> None:
        self._failures.pop(key, None)
        self._opened_at.pop(key, None)


_cb = CircuitBreaker()

# Per-feed HTTP conditional-request cache: url → {etag, last_modified}
_feed_http_cache: dict[str, dict] = {}
# Per-feed stale items (served on 304 or circuit-open)
_feed_items_cache: dict[str, list] = {}

# ---------------------------------------------------------------------------
# Scoring constants (unchanged from v1)
# ---------------------------------------------------------------------------

HIGH_PRIORITY_KEYWORDS = {
    "india": 1.5, "modi": 3.0, "rbi": 3.0, "sensex": 1.5, "nifty": 1.5,
    "rupee": 1.5, "parliament": 2.5, "lok sabha": 3.0, "rajya sabha": 3.0,
    "supreme court": 2.5, "delhi": 1.0, "mumbai": 1.0, "bengaluru": 1.0,
    "bangalore": 1.0, "hyderabad": 0.5, "chennai": 0.5, "kolkata": 0.5,
    "pune": 0.5, "budget": 2.5, "gdp": 2.0, "inflation": 2.0,
    "isro": 2.0, "upi": 1.5, "aadhaar": 1.0, "gst": 1.5,
    "market crash": 4.5, "rally": 1.0, "interest rate": 2.5, "fed": 2.0,
    "recession": 4.0, "ipo": 2.0, "stock market": 1.5, "bull": 0.5,
    "bear": 0.5, "sebi": 2.0,
    "layoff": 3.0, "job cut": 3.5, "hiring freeze": 3.5, "wfh": 0.5,
    "remote work": 0.5, "ai": 0.5, "startup": 0.5, "unicorn": 1.5,
    "funding": 0.5,
    "tariff": 2.0, "trade war": 4.0, "china": 1.5, "pakistan": 2.0,
    "us-india": 3.0, "sanctions": 3.0, "opec": 2.5, "oil price": 2.0,
    "climate": 1.0, "g20": 2.0, "brics": 1.5,
    "breaking": 4.0, "exclusive": 1.5, "major": 0.5, "crisis": 4.0,
    "emergency": 4.5, "war": 4.0, "election": 2.5, "resignation": 3.5,
    "arrested": 2.5,
}

SOURCE_AUTHORITY = {
    "BBC News": 6.0, "BBC Business": 6.0, "BBC Football": 6.0,
    "The Guardian": 6.0,
    "ESPN Soccer": 5.0,
    "Times of India": 5.0, "NDTV": 5.0, "Economic Times": 5.0,
    "Livemint": 4.5, "Moneycontrol": 4.0, "TechCrunch": 4.5,
    "Google News": 2.0, "Google News India": 2.0,
    "Google Tech": 1.5, "Google Football": 1.5,
    "Google Transfer News": 1.0, "Google Jobs/Layoffs": 1.0, "Google AI News": 1.5,
    "DeepMind": 6.0, "Mistral": 5.0, "Nvidia AI": 5.0,
    "Microsoft Research": 5.0,
}

_HARD_NEWS_VERB_RE = re.compile(
    r'\b(?:signs?|signed|passes?|passed|announces?|announced|cuts?|raises?|hikes?|'
    r'bans?|banning|arrests?|arrested|resigns?|resigned|fires?|fired|sacks?|sacked|'
    r'orders?|launches?|launched|declares?|declared|wins?|defeats?|attacks?|invaded|'
    r'crashes?|collapsed|defaults?|sanctions?|indicts?|convicted|sentenced|suspended|'
    r'impeached|ousted|dismissed|cancels?|cancelled|approves?|approved|rejects?|rejected|'
    r'kills?|killed|dies|died|explodes?|exploded|strikes?|struck|seizes?|seized)\b',
    re.IGNORECASE,
)

_SOFT_NEWS_RE = re.compile(
    r'(?:opinion|analysis|review|explainer|column)\s*[:\-]'
    r'|\bhow\s+to\s+\w+'
    r'|\b\d+\s+(?:ways|tips|reasons|things|best|must[- ]know)\b'
    r'|all\s+you\s+need\s+to\s+know'
    r'|everything\s+you\s+need'
    r"|here['\u2019]s\s+what\s+(?:you|we)"
    r'|\bguide\s+to\s+\w+'
    r'|\bwatch\s*:'
    r'|\bin\s+pictures\b'
    r'|weekly\s+(?:roundup|wrap)'
    r'|monthly\s+digest'
    r'|\ball\s+about\s+(?:the|how|why|what)\b'
    r'|\bwhy\s+(?:is|are|did|does|the|india|pakistan|china|us|iran)\b'
    r'|\bhow\s+(?:\w+\s+){1,3}(?:is|are)\s+(?:driving|reshaping|affecting|impacting|changing|redefining)\b'
    r'|\bwhat\s+(?:it\s+means|you\s+should|this\s+means|experts\s+say|the\s+data)\b'
    r'|\bwhat\s+\w+\s+must\s+do\b'
    r'|\bwhat\s+to\s+(?:look\s+out|expect|know|watch)\b'
    r'|\bfiscal\s+math\b',
    re.IGNORECASE,
)

_LIVE_BLOG_RE = re.compile(
    r'\blive\s*(?:updates?|blog|ticker|news|coverage)\s*[:\-]?'
    r'|\blive\s*:\s'
    r'|\bday\s+\d+\s+live\b'
    r'|\bfollowing\s+live\b',
    re.IGNORECASE,
)

_CASUALTY_RE = re.compile(
    r'\b\d[\d,]*\s*(?:killed|dead|died|casualties|wounded|injured|missing)\b',
    re.IGNORECASE,
)
_BIG_MONEY_RE = re.compile(
    r'(?:\$|₹|€|£)\s*\d+(?:\.\d+)?\s*(?:billion|trillion)\b'
    r'|\b\d+(?:\.\d+)?\s*(?:billion|trillion)\b',
    re.IGNORECASE,
)
_MARKET_MOVE_RE = re.compile(
    r'\b\d+(?:\.\d+)?%?\s*(?:drop|crash|plunge|surge|soar|collapses?|jumps?)\b',
    re.IGNORECASE,
)

BREAKING_SIGNALS = [
    "breaking", "breaking news", "just in", "urgent", "alert", "developing",
    "flash:", "exclusive:", "at this hour",
]

IMPORTANCE_SIGNALS = [
    "record high", "record low", "all-time high", "all-time low", "historic",
    "landmark", "unprecedented", "first ever", "first time in history",
    "catastrophic", "devastating", "collapse", "explosion", "blast",
    "earthquake", "floods", "disaster",
    "killed", "dead", "casualties", "death toll", "fatalities", "wounded",
    "missing", "plane crash", "train crash",
    "arrested", "indicted", "convicted", "sentenced", "ban", "banned",
    "parliament passes", "bill passed", "supreme court rules", "court orders",
    "declares emergency", "emergency declared", "martial law",
    "billion dollar", "trillion", "market crash", "stock market crash",
    "currency crisis", "debt default", "bankruptcy", "bank collapse",
    "resignation", "resigned", "ousted", "coup", "impeached", "fired",
    "invasion", "attack", "war declared", "ceasefire declared",
]

_FOOTBALL_OUTCOME_RE = re.compile(
    r'\b(?:\d\s*[-–]\s*\d|wins\b|win\s+\d|loses?\b|beaten\b|'
    r'victory\b|defeats?\b|thrash(?:es)?\b|hammer(?:s)?\b|demolish(?:es)?\b|'
    r'knocked\s+out\b|eliminat(?:ed|es)\b|relegated\b|promoted\b|'
    r'champions\b|title\s+winner|final\s+score|full[- ]time|ft:|'
    r'hat[- ]trick|brace\b|own\s+goal|penalty\s+shootout|extra\s+time)\b',
    re.IGNORECASE,
)

_FOOTBALL_COMPETITIONS_RE = re.compile(
    r'\b(?:premier\s+league|champions\s+league|la\s+liga|bundesliga|serie\s+a|'
    r'ligue\s+1|europa\s+league|conference\s+league|fa\s+cup|carabao\s+cup|'
    r'world\s+cup|euro\s+20\d{2}|copa\s+america|supercopa|dfb[- ]pokal|'
    r'community\s+shield|isl|afc\s+champions)\b',
    re.IGNORECASE,
)

FOOTBALL_IMPORTANCE_SIGNALS = [
    "champions league", "world cup", "euro 2024", "euro 2025", "euro 2026",
    "copa america", "europa league", "fa cup", "carabao cup", "community shield",
    "conference league", "supercopa", "dfb-pokal",
    "final", "semi-final", "semifinal", "quarter-final", "quarterfinal",
    "knockout stage", "round of 16", "last 16", "last 8", "group stage",
    "wins title", "crowned champions", "lifts the trophy", "relegated",
    "promotion", "promoted", "qualifies", "qualification", "advances",
    "knocked out", "eliminat", "title race", "title decider",
    "hat-trick", "brace", "red card", "penalty shootout", "extra time",
    "comeback", "comeback victory", "thriller", "stunner", "upset",
    "derby", "el clasico", "north west derby", "merseyside derby",
    "record transfer", "world record", "transfer confirmed", "officially signs",
    "unveiled", "done deal", "departure confirmed", "free agent signs",
    "sacked", "appointed manager", "new manager", "manager resigns",
    "interim manager",
    "injured", "ruled out", "long-term injury", "suspended", "banned",
    "returns from injury", "retirement announced", "retires",
]

AI_HIGH_IMPACT_KEYWORDS = {
    "gpt-5": 8.0, "gpt-4o": 5.0, "o3": 6.0, "o4": 7.0,
    "claude 4": 8.0, "claude 3.7": 6.0, "claude 3.5": 5.0,
    "gemini 2.0": 6.0, "gemini ultra": 6.0, "gemini 2.5": 7.0,
    "llama 4": 7.0, "llama 3": 4.0,
    "deepseek r2": 7.0, "deepseek v3": 6.0, "deepseek r1": 5.0,
    "grok 3": 6.0, "grok 2": 4.0,
    "mistral large": 5.0, "mistral small": 3.0,
    "state of the art": 4.0, "sota": 3.5, "outperforms": 3.0, "surpasses": 3.0,
    "beats gpt": 5.0, "beats claude": 5.0, "beats gemini": 5.0,
    "constitutional ai": 4.0, "alignment": 3.0, "safety": 2.0,
    "rlhf": 2.5, "dpo": 2.0, "grpo": 2.5, "reward model": 2.5,
    "chain of thought": 3.0, "reasoning": 2.5, "step-by-step": 2.0,
    "multimodal": 2.5, "vision language": 3.0, "mllm": 2.5,
    "agentic": 3.0, "multi-agent": 3.0, "tool use": 2.0, "function calling": 2.0,
    "scaling law": 3.5, "emergent": 3.0, "emergent capabilities": 4.0,
    "jailbreak": 3.0, "prompt injection": 3.0, "hallucination": 2.0,
    "rag": 2.0, "retrieval augmented": 3.0, "vector search": 2.0,
    "diffusion": 2.0, "text-to-image": 2.0, "text-to-video": 3.0,
    "benchmark": 1.5, "mmlu": 3.0, "humaneval": 3.0, "swe-bench": 3.5,
    "lora": 1.5, "qlora": 2.0, "instruction tuning": 2.0, "fine-tuning": 1.5,
    "reinforcement learning": 1.5, "large language model": 1.0,
    "open source": 1.5, "open-source": 1.5,
    "llm": 0.8, "gpt": 1.5, "transformer": 0.8, "attention mechanism": 1.5,
    "agent": 0.8, "embedding": 0.5, "retrieval": 0.5,
    "multi-agent": 1.5,
    "neural network": 0.3, "machine learning": 0.3, "deep learning": 0.3,
    "ai": 0.2, "artificial intelligence": 0.3, "ml": 0.2,
}

AI_SOURCE_TIERS = {
    "OpenAI": 8.0, "Anthropic": 8.0, "DeepMind": 8.0,
    "Google AI": 7.0, "Meta AI": 7.0, "Mistral": 6.0, "Nvidia AI": 6.0,
    "Microsoft Research": 6.0, "Apple ML": 6.5, "Amazon Science": 5.5,
    "Together AI": 4.5,
    "Lil'Log": 6.0, "The Gradient": 5.0, "HuggingFace": 5.0,
    "The Batch": 5.0, "Import AI": 5.0, "Sebastian Raschka": 5.0,
    "Simon Willison": 4.5, "Chip Huyen": 5.0, "Jay Alammar": 4.5,
    "Google Developers": 3.5, "The Keyword Google": 3.0,
    "NeurIPS Blog": 6.0, "AAAI": 5.0,
    "arXiv CS.CL": 2.0, "arXiv CS.AI": 2.0, "arXiv CS.LG": 2.0,
    "arXiv CS.IR": 1.5, "arXiv CS.CV": 2.0, "arXiv CS.RO": 1.5,
    "arXiv CS.MA": 1.5, "arXiv stat.ML": 1.5,
    "r/MachineLearning": 2.5, "r/LocalLLaMA": 2.0, "HN AI": 2.5,
    "Google AI News": 1.5,
    "HF Daily Papers": 7.0,
}

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
    "Agents": ["agent", "tool use", "function calling", "multi-agent", "agentic",
               "planning", "web agent", "code agent", "mcp", "a2a"],
    "Reasoning": ["reasoning", "chain of thought", "cot", "tree of thought",
                  "step-by-step", "math", "logic", "benchmark"],
    "Vision": ["multimodal", "vision language", "image", "video", "diffusion",
               "text-to-image", "mllm", "visual"],
}

_AI_SOTA_RE = re.compile(
    r'\b(?:state[- ]of[- ]the[- ]art|sota|outperforms?|surpasses?|'
    r'beats?\s+(?:gpt|claude|gemini|llama)|new\s+record|best[- ]in[- ]class|'
    r'first\s+to\s+achieve|breakthrough|game[- ]changing|unprecedented\s+performance)\b',
    re.IGNORECASE,
)

_AI_NOVEL_RE = re.compile(
    r'\b(?:we\s+(?:introduce|present|propose)|introducing\b|novel\s+approach|'
    r'new\s+(?:method|framework|model|architecture)|(?:releases?|released|open[- ]source[sd])\b)\b',
    re.IGNORECASE,
)

_AI_NOISE_RE = re.compile(
    r'\b(?:weekly\s+(?:digest|roundup|recap|wrap)|top\s+\d+\s+(?:papers?|tools?|models?|concepts?)|'
    r'getting\s+started|cheat\s+sheet|beginner(?:\'s)?\s+guide|'
    r'introduction\s+to\b|overview\s+of\b|course\s+(?:review|summary)|'
    r'paper\s+summary|papers\s+this\s+week|this\s+week\s+in\s+ai|'
    r'what\s+(?:is|are)\s+(?:a\s+|an\s+)?(?:llm|large\s+language|generative\s+ai|rag|ai\s+agent)|'
    r'\w+\s+explained\s+in\s+under\s+\d+|'
    r'\d+\s+\w+\s+(?:concepts?|techniques?|methods?)\s+explained)\b',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def _title_fingerprint(title: str) -> frozenset:
    STOP = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "to", "of",
        "in", "on", "at", "for", "with", "by", "from", "and", "or", "but", "not",
        "as", "it", "its", "he", "she", "they", "we", "i", "this", "that", "which",
        "who", "has", "have", "had", "will", "would", "could", "should", "after",
        "before", "over", "under", "up", "down", "says", "said",
        "news", "times", "post", "herald", "tribune", "express", "live", "today",
        "india", "daily", "online",
    }
    clean = re.sub(r'\s*\|\s*.+$', '', title)
    words = re.findall(r'\b[a-z]+\b', clean.lower())
    return frozenset(w for w in words if w not in STOP and len(w) > 2)


def _score_article(item: dict) -> float:
    title = item.get("title", "").lower()
    desc  = item.get("description", "").lower()
    pub   = item.get("published", "")
    importance = 0.0

    for kw, weight in HIGH_PRIORITY_KEYWORDS.items():
        if kw in title:
            importance += weight * 3.0
        elif kw in desc:
            importance += weight * 0.8

    for kw in BREAKING_SIGNALS:
        if kw in title:
            importance += 10.0
            break

    BROAD_RECORD_SIGNALS = {"record high", "record low", "all-time high", "all-time low"}
    for kw in IMPORTANCE_SIGNALS:
        if kw in title:
            importance += 4.0 if kw in BROAD_RECORD_SIGNALS else 8.0
        elif kw in desc:
            importance += 1.5 if kw in BROAD_RECORD_SIGNALS else 3.0

    if _HARD_NEWS_VERB_RE.search(title):
        importance += 6.0

    if _CASUALTY_RE.search(title):
        importance += 14.0
    elif _CASUALTY_RE.search(desc):
        importance += 6.0
    if _BIG_MONEY_RE.search(title):
        importance += 9.0
    elif _BIG_MONEY_RE.search(desc):
        importance += 4.0
    if _MARKET_MOVE_RE.search(title):
        importance += 8.0

    if _SOFT_NEWS_RE.search(title):
        importance -= 20.0
    if _LIVE_BLOG_RE.search(title):
        importance -= 15.0

    text = title + " " + desc
    local_foreign = [
        "county", "sheriff", "township", "borough", "precinct", "school board",
        "state trooper", "local police", "neighborhood",
    ]
    if any(lf in text for lf in local_foreign) and "india" not in text:
        importance -= 25.0

    is_breaking = any(kw in title for kw in BREAKING_SIGNALS)
    age_h = None
    if pub:
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(pub)).total_seconds() / 3600
        except Exception:
            pass

    if is_breaking:
        if age_h is None:
            recency_mult = 0.7
        else:
            recency_mult = max(2.5 * math.exp(-0.23 * max(age_h, 0)), 0.5)
    else:
        recency_mult = 1.0

    source_boost = SOURCE_AUTHORITY.get(item.get("source", ""), 1.5)
    return max(importance, 0.0) * recency_mult + source_boost


def _score_football_article(item: dict) -> float:
    title = item.get("title", "").lower()
    desc  = item.get("description", "").lower()
    pub   = item.get("published", "")
    importance = 0.0

    for kw in FOOTBALL_IMPORTANCE_SIGNALS:
        if kw in title:
            importance += 10.0
        elif kw in desc:
            importance += 4.0

    for kw in BREAKING_SIGNALS:
        if kw in title:
            importance += 10.0
            break

    if _BIG_MONEY_RE.search(title):
        importance += 12.0
    elif _BIG_MONEY_RE.search(desc):
        importance += 5.0

    has_outcome = bool(_FOOTBALL_OUTCOME_RE.search(title))
    has_competition = bool(_FOOTBALL_COMPETITIONS_RE.search(title) or _FOOTBALL_COMPETITIONS_RE.search(desc))
    if has_outcome and has_competition:
        importance *= 2.5
    elif has_outcome:
        importance *= 1.5

    if _SOFT_NEWS_RE.search(title):
        importance -= 20.0

    age_h = None
    if pub:
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(pub)).total_seconds() / 3600
        except Exception:
            pass
    if age_h is None:
        recency_mult = 0.5
    else:
        recency_mult = max(1.3 * math.exp(-0.039 * max(age_h, 0)), 0.1)

    source_boost = SOURCE_AUTHORITY.get(item.get("source", ""), 1.5)
    return max(importance, 0.0) * recency_mult + source_boost


def _score_ai_article(item: dict) -> float:
    title  = item.get("title", "").lower()
    desc   = item.get("description", "").lower()
    pub    = item.get("published", "")
    source = item.get("source", "")
    importance = 0.0

    kw_importance = 0.0
    for kw, weight in AI_HIGH_IMPACT_KEYWORDS.items():
        if kw in title:
            kw_importance += weight * 3.0
        elif kw in desc:
            kw_importance += weight * 0.8
    importance += min(kw_importance, 12.0)

    if _AI_SOTA_RE.search(title):
        importance += 8.0
    elif _AI_SOTA_RE.search(desc):
        importance += 3.0

    if _AI_NOVEL_RE.search(title):
        importance += 5.0

    is_arxiv = source.startswith("arXiv")
    has_signal = _AI_SOTA_RE.search(title) or _AI_NOVEL_RE.search(title)
    if is_arxiv and not has_signal:
        importance -= 6.0

    if _AI_NOISE_RE.search(title):
        importance -= 15.0
    if _SOFT_NEWS_RE.search(title):
        importance -= 10.0

    age_h = None
    if pub:
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(pub)).total_seconds() / 3600
        except Exception:
            pass
    if age_h is None:
        recency_mult = 0.5
    else:
        recency_mult = max(2.0 * math.exp(-0.0145 * max(age_h, 0)), 0.1)

    source_boost = AI_SOURCE_TIERS.get(item.get("source", ""), 1.5)
    return max(importance, 0.0) * recency_mult + source_boost


def _tag_article(item: dict) -> str:
    title = item.get("title", "").lower()
    desc  = item.get("description", "").lower()
    text  = title + " " + desc
    best_tag, best_score = "", 0.0
    for tag, keywords in CATEGORY_TAGS.items():
        score = 0.0
        for kw in keywords:
            if kw in text:
                weight = len(kw.split())
                score += weight * 3.0 if kw in title else weight * 1.0
        if score > best_score:
            best_score, best_tag = score, tag
    return best_tag or "General"


def _tag_ai_article(item: dict) -> str:
    text = (item.get("title", "") + " " + item.get("description", "")).lower()
    best_tag, best_count = "", 0
    for tag, keywords in AI_CATEGORY_TAGS.items():
        count = sum(1 for kw in keywords if kw in text)
        if count > best_count:
            best_count, best_tag = count, tag
    return best_tag or "ML"


# ---------------------------------------------------------------------------
# Google News URL resolver
# ---------------------------------------------------------------------------

async def _resolve_google_news_url(gn_url: str) -> str:
    if _gnd_decoder is None:
        return gn_url
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: _gnd_decoder(gn_url, interval=None)
        )
        if isinstance(result, dict) and result.get("status") and result.get("decoded_url"):
            return result["decoded_url"]
    except Exception:
        pass
    return gn_url


# ---------------------------------------------------------------------------
# Feed helpers
# ---------------------------------------------------------------------------

async def _fetch_feed(source_name: str, url: str) -> list[dict]:
    """Fetch one RSS feed with ETag/LM conditional requests and circuit breaker."""
    if _cb.is_open(url):
        return _feed_items_cache.get(url, [])

    req_headers: dict[str, str] = {}
    cached_hdrs = _feed_http_cache.get(url, {})
    if cached_hdrs.get("etag"):
        req_headers["If-None-Match"] = cached_hdrs["etag"]
    if cached_hdrs.get("last_modified"):
        req_headers["If-Modified-Since"] = cached_hdrs["last_modified"]

    try:
        resp = await _http_client.get(url, headers=req_headers)

        if resp.status_code == 304:
            _cb.record_success(url)
            return _feed_items_cache.get(url, [])

        resp.raise_for_status()
        _cb.record_success(url)

        # Store conditional-request headers for next call
        new_hdrs: dict[str, str] = {}
        if resp.headers.get("etag"):
            new_hdrs["etag"] = resp.headers["etag"]
        if resp.headers.get("last-modified"):
            new_hdrs["last_modified"] = resp.headers["last-modified"]
        if new_hdrs:
            _feed_http_cache[url] = new_hdrs

        content = resp.content
    except Exception:
        _cb.record_failure(url)
        return _feed_items_cache.get(url, [])

    # feedparser is CPU-bound; run in executor to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    try:
        feed = await loop.run_in_executor(None, lambda: feedparser.parse(content))
    except Exception:
        return _feed_items_cache.get(url, [])

    items = []
    gn_indices = []

    for entry in feed.entries[:15]:
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
            for lnk in entry.links:
                if "image" in lnk.get("type", ""):
                    thumb = lnk.get("href", "")
                    break
        if not thumb and hasattr(entry, "enclosures"):
            for enc in entry.enclosures:
                if "image" in enc.get("type", ""):
                    thumb = enc.get("href", "")
                    break

        published = ""
        dt = entry.get("published_parsed") or entry.get("updated_parsed")
        if dt:
            try:
                published = datetime(*dt[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass

        desc = entry.get("summary", "") or entry.get("description", "")
        desc = re.sub(r"<[^>]+>", "", desc).strip()
        if len(desc) > 220:
            desc = desc[:217] + "..."

        link = entry.get("link", "")
        # Estimate reading time from description length as proxy for full article
        # Average article ~800 words; scale from snippet (220 chars ≈ 40 words)
        desc_words = len(desc.split())
        estimated_wc = max(200, desc_words * 20)  # 1 snippet word ≈ 20 article words
        reading_time = max(1, math.ceil(estimated_wc / 200))
        idx = len(items)
        items.append({
            "title": entry.get("title", ""),
            "link": link,
            "source": source_name,
            "published": published,
            "description": desc,
            "thumbnail": thumb,
            "readingTime": reading_time,
        })
        if "news.google.com" in link:
            gn_indices.append(idx)

    # Resolve Google News redirect URLs in parallel
    if gn_indices:
        resolved = await asyncio.gather(
            *[_resolve_google_news_url(items[i]["link"]) for i in gn_indices],
            return_exceptions=True,
        )
        for i, r in zip(gn_indices, resolved):
            if isinstance(r, str):
                items[i]["link"] = r

    _feed_items_cache[url] = items
    return items


def _process_feeds(all_items: list[dict], category: str) -> list[dict]:
    """Deduplicate, score, cross-source-boost, and rank a flat list of feed items."""
    all_fingerprints = [_title_fingerprint(item["title"]) for item in all_items]
    all_sources      = [item.get("source", "") for item in all_items]

    seen_titles: set[str] = set()
    unique: list[dict] = []
    unique_indices: list[int] = []
    is_ai       = category == "ai_research"
    is_football = category == "football"

    for idx, item in enumerate(all_items):
        key = re.sub(r"\W+", "", item["title"].lower())[:50]
        if key not in seen_titles:
            seen_titles.add(key)
            if is_ai:
                item["tag"]   = _tag_ai_article(item)
                item["score"] = _score_ai_article(item)
            elif is_football:
                item["tag"]   = _tag_article(item)
                item["score"] = _score_football_article(item)
            else:
                item["tag"]   = _tag_article(item)
                item["score"] = _score_article(item)
            item["_fp"] = all_fingerprints[idx]
            unique.append(item)
            unique_indices.append(idx)

    def _cross_source_name(src: str) -> str:
        return "arXiv" if src.startswith("arXiv") else src

    for i, item in enumerate(unique):
        fp          = all_fingerprints[unique_indices[i]]
        item_source = _cross_source_name(all_sources[unique_indices[i]])
        if len(fp) < 2:
            continue
        seen_cross: set[str] = set()
        for j, (other_fp, other_src) in enumerate(zip(all_fingerprints, all_sources)):
            norm_src = _cross_source_name(other_src)
            if (j != unique_indices[i]
                    and norm_src != item_source
                    and norm_src not in seen_cross
                    and len(other_fp) > 0
                    and len(fp & other_fp) / max(len(fp), len(other_fp)) >= 0.45):
                seen_cross.add(norm_src)
        cross_count = len(seen_cross)
        if cross_count > 0:
            item["score"] = item.get("score", 0) + min(cross_count * 3.0, 12.0)

    unique.sort(key=lambda x: x.get("score", 0), reverse=True)

    if category == "top_news":
        cluster_counts: list[int] = []
        cluster_fps: list[frozenset] = []
        diverse: list[dict] = []
        MAX_PER_CLUSTER = 2
        for item in unique:
            fp = item.get("_fp", frozenset())
            cluster_slot = -1
            for ci, cfp in enumerate(cluster_fps):
                if len(fp) > 0 and len(cfp) > 0:
                    if len(fp & cfp) / max(len(fp), len(cfp)) >= 0.50:
                        cluster_slot = ci
                        break
            if cluster_slot == -1:
                cluster_fps.append(fp)
                cluster_counts.append(1)
                diverse.append(item)
            elif cluster_counts[cluster_slot] < MAX_PER_CLUSTER:
                cluster_counts[cluster_slot] += 1
                diverse.append(item)
        unique = diverse

    result = unique[:50]
    for item in result:
        item.pop("_fp", None)
    return result


async def _fetch_all_feeds(category: str) -> list[dict]:
    """Return category feed items from cache, or fetch and process all."""
    cached = _cached(f"feeds_{category}")
    if cached is not None:
        return cached

    feeds = RSS_FEEDS.get(category, [])
    tasks = [asyncio.create_task(_fetch_feed(n, u)) for n, u in feeds]

    hf_task = None
    if category == "ai_research":
        hf_task = asyncio.create_task(_fetch_hf_daily_papers())

    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_items: list[dict] = []
    for r in results:
        if isinstance(r, list):
            all_items.extend(r)

    if hf_task is not None:
        hf_result = await hf_task
        if isinstance(hf_result, list):
            for p in hf_result:
                p["source"] = "HF Daily Papers"
            all_items.extend(hf_result)

    result = _process_feeds(all_items, category)
    _set_cache(f"feeds_{category}", result)
    return result


# ---------------------------------------------------------------------------
# Stock helpers
# ---------------------------------------------------------------------------

_YF_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
_YF_HEADERS = {"User-Agent": HEADERS["User-Agent"], "Accept": "application/json"}

# Crumb authentication — Yahoo Finance requires this since 2024 to avoid 429s
_YF_CRUMB: str | None = None
_YF_COOKIES: str = ""
_YF_CRUMB_TS: float = 0.0
_YF_CRUMB_TTL = 3600.0   # crumb valid ~1 hour
_YF_CRUMB_LOCK = asyncio.Lock()


async def _get_yf_crumb() -> tuple[str | None, str]:
    """Return (crumb, cookie_str).  Fetches fresh crumb if stale; uses lock to
    avoid thundering-herd on startup when all tickers are fetched concurrently."""
    global _YF_CRUMB, _YF_COOKIES, _YF_CRUMB_TS
    if _YF_CRUMB and time.time() - _YF_CRUMB_TS < _YF_CRUMB_TTL:
        return _YF_CRUMB, _YF_COOKIES
    async with _YF_CRUMB_LOCK:
        # Double-check after acquiring lock (another coro may have refreshed)
        if _YF_CRUMB and time.time() - _YF_CRUMB_TS < _YF_CRUMB_TTL:
            return _YF_CRUMB, _YF_COOKIES
        try:
            # Step 1: land on finance.yahoo.com to receive session cookies
            r = await _http_client.get(
                "https://finance.yahoo.com/",
                headers={**HEADERS, "Accept": "text/html,application/xhtml+xml,*/*"},
                timeout=10.0,
            )
            cookie_str = "; ".join(f"{k}={v}" for k, v in r.cookies.items())
            # Step 2: exchange cookies for a crumb token
            r2 = await _http_client.get(
                "https://query2.finance.yahoo.com/v1/test/getcrumb",
                headers={**_YF_HEADERS, "Cookie": cookie_str},
                timeout=6.0,
            )
            crumb = r2.text.strip().strip('"')
            if crumb and 3 < len(crumb) < 50 and r2.status_code == 200:
                _YF_CRUMB = crumb
                _YF_COOKIES = cookie_str
                _YF_CRUMB_TS = time.time()
                return crumb, cookie_str
        except Exception:
            pass
        return None, ""


async def _fetch_one_stock(symbol: str, label: str) -> dict | None:
    """Fetch a single ticker via Yahoo Finance chart API.
    Uses crumb + cookie auth to avoid IP-based 429 rate-limiting."""
    crumb, cookie_str = await _get_yf_crumb()
    encoded = urllib.parse.quote(symbol)
    params  = {"interval": "1d", "range": "1d", "includePrePost": "false"}
    if crumb:
        params["crumb"] = crumb
    req_headers = dict(_YF_HEADERS)
    if cookie_str:
        req_headers["Cookie"] = cookie_str
    for host in _YF_HOSTS:
        try:
            resp = await _http_client.get(
                f"https://{host}/v8/finance/chart/{encoded}",
                params=params, headers=req_headers, timeout=6.0,
            )
            if resp.status_code == 429:
                # Crumb may have expired — invalidate so next call refreshes
                _YF_CRUMB_TS = 0.0
                continue
            if resp.status_code != 200:
                return None
            data   = resp.json()
            result = data.get("chart", {}).get("result")
            if not result:
                return None
            meta  = result[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            prev  = meta.get("previousClose") or meta.get("chartPreviousClose")
            if price is None:
                return None
            change     = price - prev if prev else 0.0
            change_pct = (change / prev * 100) if prev else 0.0
            return {
                "label":      label,
                "symbol":     symbol,
                "price":      round(float(price), 2),
                "change":     round(float(change), 2),
                "change_pct": round(float(change_pct), 2),
                "currency":   meta.get("currency", "USD") or "USD",
            }
        except Exception:
            continue
    return None


_NSE_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept":     "application/json",
    "Referer":    "https://www.nseindia.com/",
}

# Mapping: NSE index name → (app label, YF symbol, currency)
_NSE_INDEX_MAP = {
    "NIFTY 50":   ("NIFTY 50",   "^NSEI",    "INR"),
    "NIFTY BANK": ("BANK NIFTY", "^NSEBANK",  "INR"),
    "NIFTY IT":   ("NIFTY IT",   "^CNXIT",    "INR"),
}

# Mapping: world-indices symbol → (app label, app symbol, currency)
_WI_SYMBOL_MAP = {
    "^GSPC":  ("S&P 500",    "^GSPC",  "USD"),
    "^IXIC":  ("NASDAQ",     "^IXIC",  "USD"),
    "^DJI":   ("DOW JONES",  "^DJI",   "USD"),
    "GC=F":   ("GOLD",       "GC=F",   "USD"),
    "BZ=F":   ("BRENT CRUDE","BZ=F",   "USD"),
    "^BSESN": ("SENSEX",     "^BSESN", "INR"),  # price computed from change data
}


async def _fetch_india_stocks_nse() -> list[dict]:
    """NSE India allIndices API fallback — no auth required, covers NIFTY 50/BANK/IT."""
    try:
        resp = await _http_client.get(
            "https://www.nseindia.com/api/allIndices",
            headers=_NSE_HEADERS, timeout=8.0,
        )
        if resp.status_code != 200:
            return []
        index_map = {item["index"]: item for item in resp.json().get("data", [])}
        results: list[dict] = []
        for nse_name, (label, symbol, currency) in _NSE_INDEX_MAP.items():
            idx = index_map.get(nse_name)
            if not idx:
                continue
            last   = float(idx.get("last")          or 0)
            prev   = float(idx.get("previousClose") or last)
            change = float(idx.get("variation")     or (last - prev))
            pct    = float(idx.get("percentChange") or ((change / prev * 100) if prev else 0))
            if not last:
                continue
            results.append({
                "label":      label,
                "symbol":     symbol,
                "price":      round(last,   2),
                "change":     round(change, 2),
                "change_pct": round(pct,    2),
                "currency":   currency,
            })
        return results
    except Exception:
        return []


async def _fetch_stocks_html(target_symbols: set[str]) -> list[dict]:
    """Yahoo Finance world-indices HTML fallback — one 1MB page covers US + commodities."""
    try:
        resp = await _http_client.get(
            "https://finance.yahoo.com/world-indices/",
            headers={**HEADERS, "Accept": "text/html,application/xhtml+xml,*/*"},
            timeout=12.0,
        )
        if resp.status_code != 200:
            return []
        html = resp.text
        results: list[dict] = []
        for yf_sym, (label, app_sym, currency) in _WI_SYMBOL_MAP.items():
            if app_sym not in target_symbols:
                continue
            esc = re.escape(yf_sym)
            def _val(field: str, _esc: str = esc, _html: str = html) -> str | None:
                m = (re.search(rf'data-symbol="{_esc}"[^>]*data-field="{field}"[^>]*data-value="([^"]+)"', _html) or
                     re.search(rf'data-field="{field}"[^>]*data-symbol="{_esc}"[^>]*data-value="([^"]+)"', _html))
                return m.group(1) if m else None
            price_s  = _val("regularMarketPrice")
            change_s = _val("regularMarketChange")
            pct_s    = _val("regularMarketChangePercent")
            if price_s is None and change_s and pct_s:
                # Compute price from change + percent (e.g. SENSEX has no direct price tag)
                try:
                    chg = float(change_s)
                    pct_v = float(pct_s)
                    if pct_v:
                        prev = chg / (pct_v / 100)
                        price_s = str(round(prev + chg, 2))
                except (ValueError, ZeroDivisionError):
                    pass
            if price_s is None:
                continue
            try:
                price  = float(price_s)
                change = float(change_s) if change_s else 0.0
                pct    = float(pct_s)    if pct_s    else 0.0
            except ValueError:
                continue
            results.append({
                "label":      label,
                "symbol":     app_sym,
                "price":      round(price,  2),
                "change":     round(change, 2),
                "change_pct": round(pct,    2),
                "currency":   currency,
            })
        return results
    except Exception:
        return []


async def _fetch_stocks(market: str) -> list[dict]:
    cache_key = f"stocks_{market}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached
    symbols = STOCK_SYMBOLS.get(market, [])
    tasks = [_fetch_one_stock(sym, label) for label, sym in symbols]
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    order = {label: i for i, (label, _) in enumerate(symbols)}
    results = sorted(
        [r for r in raw if isinstance(r, dict)],
        key=lambda x: order.get(x["label"], 99),
    )
    if results:
        _set_cache(cache_key, results)
        return results

    # --- Yahoo Finance rate-limited / unreachable — try fallback sources ---
    fallback: list[dict] = []
    if market == "india":
        # NSE India: NIFTY 50, BANK NIFTY, NIFTY IT; SENSEX from world-indices HTML
        nse_data = await _fetch_india_stocks_nse()
        sensex_data = await _fetch_stocks_html({"^BSESN"})
        seen_labels = {r["label"] for r in nse_data}
        fallback = nse_data + [r for r in sensex_data if r["label"] not in seen_labels]
    elif market in ("us", "commodities"):
        target_syms = {sym for _, sym in symbols}
        fallback = await _fetch_stocks_html(target_syms)

    if fallback:
        _set_cache(cache_key, fallback)
        # Sort by the order defined in STOCK_SYMBOLS
        fallback.sort(key=lambda x: order.get(x["label"], 99))
        return fallback

    # Last resort: return stale cached data
    stale = _cache.get(cache_key)
    if stale:
        return stale["data"]
    return []


# ---------------------------------------------------------------------------
# Football scores helpers
# ---------------------------------------------------------------------------

FOOTBALL_LEAGUES = [
    ("eng.1", "Premier League", "PL"),
    ("uefa.champions", "Champions League", "UCL"),
    ("esp.1", "La Liga", "LaLiga"),
    ("ger.1", "Bundesliga", "BL"),
    ("ita.1", "Serie A", "SA"),
    ("fra.1", "Ligue 1", "L1"),
    ("uefa.europa", "Europa League", "UEL"),
    ("uefa.europa.conf", "Conference League", "UECL"),
    ("fifa.friendly", "International", "INTL"),
    ("uefa.nations", "Nations League", "UNL"),
]

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"

TOP_TEAMS = {
    "PL": {"arsenal", "man city", "liverpool", "chelsea", "man united",
           "newcastle", "tottenham", "aston villa", "brighton", "nottm forest"},
    "UCL": None,
    "UEL": None,
    "UECL": None,
    "LaLiga": {"real madrid", "barcelona", "atletico", "athletic", "villarreal",
               "real sociedad", "betis", "mallorca"},
    "BL": {"bayern", "leverkusen", "dortmund", "stuttgart", "rb leipzig",
           "frankfurt", "freiburg"},
    "SA": {"inter milan", "napoli", "atalanta", "juventus", "ac milan",
           "lazio", "roma", "fiorentina", "bologna"},
    "L1": {"psg", "paris saint-germain", "marseille", "monaco", "lille", "lyon"},
    "INTL": {"brazil", "argentina", "france", "england", "germany", "spain",
             "portugal", "india", "italy", "netherlands", "belgium"},
    "UNL": {"brazil", "argentina", "france", "england", "germany", "spain",
            "portugal", "india", "italy", "netherlands", "belgium"},
}


async def _fetch_league_scores(league_code: str, league_name: str, short: str,
                                date_range: str) -> list[dict]:
    url = f"{ESPN_SCOREBOARD_URL.format(league=league_code)}?dates={date_range}&limit=50"
    try:
        resp = await _http_client.get(url)
        data = resp.json()
    except Exception:
        return []

    matches = []
    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        status_obj = comp.get("status", {}).get("type", {})
        state  = status_obj.get("state", "")
        detail = status_obj.get("shortDetail", "")
        if state not in ("post", "in"):
            continue
        teams = comp.get("competitors", [])
        if len(teams) < 2:
            continue
        home = teams[0]
        away = teams[1]
        matches.append({
            "event_id":    event.get("id", ""),
            "league_code": league_code,
            "home":        home["team"].get("shortDisplayName", home["team"].get("displayName", "?")),
            "away":        away["team"].get("shortDisplayName", away["team"].get("displayName", "?")),
            "home_score":  home.get("score", "?"),
            "away_score":  away.get("score", "?"),
            "home_logo":   home["team"].get("logo", ""),
            "away_logo":   away["team"].get("logo", ""),
            "league":      league_name,
            "league_short": short,
            "status":      "FT" if state == "post" else detail,
            "date":        event.get("date", ""),
        })
    return matches


async def _fetch_all_scores() -> list[dict]:
    cached = _cached("football_scores", ttl=1800)
    if cached is not None:
        return cached

    now   = datetime.now(timezone.utc)
    start = now - timedelta(days=7)
    date_range = f"{start.strftime('%Y%m%d')}-{now.strftime('%Y%m%d')}"

    tasks = [
        asyncio.create_task(_fetch_league_scores(code, name, short, date_range))
        for code, name, short in FOOTBALL_LEAGUES
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_matches: list[dict] = []
    club_match_count = 0
    for (code, name, short), r in zip(FOOTBALL_LEAGUES, results):
        if isinstance(r, list):
            is_intl = short in ("INTL", "UNL")
            if not is_intl:
                club_match_count += len(r)
            all_matches.extend(r)

    if club_match_count >= 8:
        all_matches = [m for m in all_matches if m["league_short"] not in ("INTL", "UNL")]

    filtered = []
    for m in all_matches:
        top = TOP_TEAMS.get(m["league_short"])
        if top is None:
            filtered.append(m)
            continue
        home_lc = m["home"].lower()
        away_lc = m["away"].lower()
        if any(t in home_lc or home_lc in t for t in top) or \
           any(t in away_lc or away_lc in t for t in top):
            filtered.append(m)

    filtered.sort(key=lambda x: x.get("date", ""), reverse=True)
    _set_cache("football_scores", filtered)
    return filtered


# ---------------------------------------------------------------------------
# HuggingFace trending
# ---------------------------------------------------------------------------

async def _fetch_hf_daily_papers() -> list[dict]:
    try:
        resp = await _http_client.get("https://huggingface.co/api/daily_papers")
        if resp.status_code != 200:
            return []
        papers = resp.json()
        items = []
        for p in papers[:30]:
            paper    = p.get("paper", {})
            title    = paper.get("title", "")
            abstract = paper.get("summary", "")
            arxiv_id = paper.get("id", "")
            pub_date = paper.get("publishedAt", "")
            upvotes  = paper.get("upvotes", 0)   # upvotes lives inside paper{}, not root
            thumbnail = p.get("thumbnail", "")    # thumbnail is at root level
            if not title:
                continue
            items.append({
                "title":       title,
                "link":        f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
                "source":      "HF Daily Papers",
                "published":   pub_date,
                "description": (abstract[:220] + "...") if len(abstract) > 220 else abstract,
                "thumbnail":   thumbnail,
                "upvotes":     upvotes,
                "paper_id":    arxiv_id,
            })
        return items
    except Exception:
        return []


async def _fetch_hf_trending_models() -> list[dict]:
    try:
        resp = await _http_client.get(
            "https://huggingface.co/api/models",
            params={"sort": "likes", "direction": "-1", "limit": "15"},
        )
        if resp.status_code != 200:
            return []
        models = resp.json()
        return [
            {
                "model_id": m.get("modelId", "") or m.get("id", ""),
                "pipeline": m.get("pipeline_tag", ""),
                "tags":     m.get("tags", [])[:5],
                "likes":    m.get("likes", 0),
                "downloads": m.get("downloads", 0),
                "link":     f"https://huggingface.co/{m.get('modelId', '') or m.get('id', '')}",
            }
            for m in models
        ]
    except Exception:
        return []


async def _fetch_trending() -> dict:
    cached = _cached("trending_data", ttl=3600)
    if cached is not None:
        return cached

    papers, models = await asyncio.gather(
        _fetch_hf_daily_papers(),
        _fetch_hf_trending_models(),
        return_exceptions=True,
    )
    if not isinstance(papers, list):
        papers = []
    if not isinstance(models, list):
        models = []

    for p in papers:
        p["tag"]   = _tag_ai_article(p)
        p["score"] = _score_ai_article(p)
        upvotes = p.get("upvotes", 0)
        if upvotes > 0:
            p["score"] += min(math.log2(upvotes + 1) * 2.0, 10.0)

    papers.sort(key=lambda x: x.get("score", 0), reverse=True)
    result = {"papers": papers, "models": models}
    _set_cache("trending_data", result)
    return result


# ---------------------------------------------------------------------------
# Article helpers
# ---------------------------------------------------------------------------

def _extract_ld_json(html: str) -> dict | None:
    ld_blocks = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    for block in ld_blocks:
        try:
            data = json.loads(block)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                atype = item.get("@type", "")
                if atype in ("NewsArticle", "Article", "ReportageNewsArticle", "WebPage") \
                        or "Article" in str(atype):
                    body = item.get("articleBody", "")
                    if body and len(body) > 100:
                        authors = []
                        raw_author = item.get("author", [])
                        if isinstance(raw_author, dict):
                            raw_author = [raw_author]
                        if isinstance(raw_author, list):
                            for a in raw_author:
                                if isinstance(a, dict):
                                    authors.append(a.get("name", ""))
                                elif isinstance(a, str):
                                    authors.append(a)
                        img = ""
                        raw_img = item.get("image", item.get("thumbnailUrl", ""))
                        if isinstance(raw_img, dict):
                            img = raw_img.get("url", "")
                        elif isinstance(raw_img, list) and raw_img:
                            first = raw_img[0]
                            img = first.get("url", "") if isinstance(first, dict) else str(first)
                        elif isinstance(raw_img, str):
                            img = raw_img
                        return {
                            "title":        item.get("headline", ""),
                            "authors":      [a for a in authors if a],
                            "publish_date": item.get("datePublished", ""),
                            "top_image":    img,
                            "text":         body,
                        }
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _extract_og_meta(html: str) -> dict:
    def _meta(prop):
        m = re.search(
            rf'<meta[^>]*(?:property|name)=["\'](?:og:)?{prop}["\'][^>]*content=["\']([^"\']+)',
            html, re.I,
        )
        return m.group(1) if m else ""
    return {
        "title":          _meta("title"),
        "description":    _meta("description"),
        "image":          _meta("image"),
        "author":         _meta("author"),
        "published_time": _meta("article:published_time"),
    }


def _fallback_extract_from_html(html: str) -> str:
    try:
        m = re.search(r"<article[^>]*>(.*?)</article>", html, re.DOTALL)
        if not m:
            m = re.search(
                r'<div[^>]*(?:class|id)=["\'][^"\']*(?:article|story|content|post)[^"\']*["\'][^>]*>(.*?)</div>',
                html, re.DOTALL,
            )
        if m:
            content = m.group(1)
            paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", content, re.DOTALL)
            text = "\n\n".join(
                re.sub(r"<[^>]+>", "", p).strip()
                for p in paragraphs if len(p.strip()) > 30
            )
            if len(text) > 100:
                return text
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# SSRF protection for image proxy
# ---------------------------------------------------------------------------

def _is_safe_url(url: str) -> bool:
    """Return True only if the URL is http(s) and resolves to a public IP."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        ip_str = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
        return True
    except Exception:
        return False


def _encode_webp(content: bytes, max_w: int = 400, max_h: int = 300) -> bytes:
    """Resize image and encode as WebP. CPU-bound — run in executor."""
    _ensure_pil()
    import io
    buf_in  = io.BytesIO(content)
    img = _PILImage.open(buf_in)
    img = img.convert("RGB")
    img.thumbnail((max_w, max_h), _PILImage.Resampling.LANCZOS)
    buf_out = io.BytesIO()
    img.save(buf_out, format="WebP", quality=80)
    return buf_out.getvalue()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/sw.js")
async def serve_sw():
    """Serve service worker from root so its scope covers the entire app."""
    sw_path = os.path.join(os.path.dirname(__file__), "static", "js", "sw.js")
    try:
        with open(sw_path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return Response(status_code=404)
    return Response(
        content=content,
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/manifest.json")
async def serve_manifest():
    path = os.path.join(os.path.dirname(__file__), "static", "manifest.json")
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return Response(status_code=404)
    return Response(content=content, media_type="application/json")


@app.get("/api/news/{category}")
async def api_news(category: str):
    if category not in RSS_FEEDS:
        return JSONResponse({"error": "Unknown category"}, status_code=400)
    return JSONResponse(await _fetch_all_feeds(category))


@app.get("/api/news/stream/{category}")
async def api_news_stream(category: str):
    """SSE endpoint: emits partial results as feeds arrive, final 'done' event."""
    if category not in RSS_FEEDS:
        return JSONResponse({"error": "Unknown category"}, status_code=400)

    cache_key = f"feeds_{category}"

    async def event_gen():
        # Serve from cache immediately if fresh
        cached = _cached(cache_key)
        if cached is not None:
            yield f"data: {json.dumps(cached)}\n\n"
            yield "event: done\ndata: {}\n\n"
            return

        feeds = RSS_FEEDS.get(category, [])
        queue: asyncio.Queue = asyncio.Queue()
        task_count = len(feeds) + (1 if category == "ai_research" else 0)

        async def fetch_one(name: str, url: str) -> None:
            items = await _fetch_feed(name, url)
            await queue.put(items)

        async def fetch_hf() -> None:
            papers = await _fetch_hf_daily_papers()
            for p in papers:
                p["source"] = "HF Daily Papers"
            await queue.put(papers)

        tasks = [asyncio.create_task(fetch_one(n, u)) for n, u in feeds]
        if category == "ai_research":
            tasks.append(asyncio.create_task(fetch_hf()))

        all_items: list[dict] = []
        done_count = 0
        last_emit = time.monotonic()

        try:
            while done_count < task_count:
                try:
                    batch = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    break
                all_items.extend(batch)
                done_count += 1

                now = time.monotonic()
                # Emit partial every 4 feeds or every 2 seconds
                if done_count % 4 == 0 or (now - last_emit) >= 2.0:
                    partial = _process_feeds(list(all_items), category)
                    yield f"data: {json.dumps(partial)}\n\n"
                    last_emit = now
        finally:
            for t in tasks:
                t.cancel()

        final = _process_feeds(all_items, category)
        _set_cache(cache_key, final)
        yield f"data: {json.dumps(final)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/stocks/all")
async def api_stocks_all():
    results = await asyncio.gather(*[_fetch_stocks(m) for m in STOCK_SYMBOLS])
    return JSONResponse(dict(zip(STOCK_SYMBOLS.keys(), results)))


@app.get("/api/stocks/{market}")
async def api_stocks(market: str):
    if market not in STOCK_SYMBOLS:
        return JSONResponse({"error": "Unknown market"}, status_code=400)
    return JSONResponse(await _fetch_stocks(market))


@app.get("/api/scores")
async def api_scores():
    return JSONResponse(await _fetch_all_scores())


@app.get("/api/trending")
async def api_trending():
    return JSONResponse(await _fetch_trending())


@app.get("/api/match/{league}/{event_id}")
async def api_match(league: str, event_id: str):
    cache_key = f"match_{league}_{event_id}"
    cached = _cached(cache_key, ttl=3600)
    if cached is not None:
        return JSONResponse(cached)

    summary_url = (
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/"
        f"{league}/summary?event={event_id}"
    )
    try:
        resp  = await _http_client.get(summary_url)
        sdata = resp.json()
    except Exception:
        return JSONResponse({"error": "Failed to fetch match data"}, status_code=502)

    header      = sdata.get("header", {})
    comps       = header.get("competitions", [{}])[0]
    competitors = comps.get("competitors", [])

    teams = []
    for c in competitors:
        t = c.get("team", {})
        logos = t.get("logos", [])
        teams.append({
            "name":      t.get("displayName", "?"),
            "short":     t.get("abbreviation", ""),
            "score":     c.get("score", "?"),
            "logo":      logos[0].get("href", "") if logos else "",
            "home_away": c.get("homeAway", ""),
        })

    STAT_KEYS = {
        "Possession": "Possession", "SHOTS": "Total Shots",
        "ON GOAL": "Shots on Target", "Corner Kicks": "Corner Kicks",
        "Fouls": "Fouls", "Yellow Cards": "Yellow Cards",
        "Red Cards": "Red Cards", "Offsides": "Offsides", "Saves": "Saves",
        "Pass Completion %": "Pass Completion %", "Accurate Passes": "Accurate Passes",
    }
    team_stats = []
    for t in sdata.get("boxscore", {}).get("teams", []):
        stat_map = {s["label"]: s["displayValue"] for s in t.get("statistics", [])}
        team_stats.append({
            "name":  t.get("team", {}).get("displayName", "?"),
            "stats": {display: stat_map.get(api_key, "-") for api_key, display in STAT_KEYS.items()},
        })

    key_events = []
    for ke in sdata.get("keyEvents", []):
        etype = ke.get("type", {}).get("text", "")
        if etype not in ("Goal", "Yellow Card", "Red Card", "Substitution",
                         "Penalty - Scored", "Penalty - Missed", "Own Goal"):
            continue
        athletes = ke.get("participants", [])
        athlete_name = athletes[0].get("athlete", {}).get("displayName", "") if athletes else ""
        key_events.append({
            "type":   etype,
            "clock":  ke.get("clock", {}).get("displayValue", ""),
            "team":   ke.get("team", {}).get("displayName", ""),
            "player": athlete_name,
        })

    gi    = sdata.get("gameInfo", {})
    venue = gi.get("venue", {})
    result = {
        "teams": teams, "stats": team_stats, "events": key_events,
        "venue": venue.get("fullName", ""), "attendance": gi.get("attendance", ""),
    }
    _set_cache(cache_key, result)
    return JSONResponse(result)


@app.get("/api/article")
async def api_article(url: str = Query(...)):
    url = url.strip()
    if not url:
        return JSONResponse({"error": "Missing url parameter"}, status_code=400)

    if "news.google.com" in url:
        url = await _resolve_google_news_url(url)

    cache_key = f"article_{url}"
    cached = _cached(cache_key, ttl=7200)
    if cached is not None:
        return JSONResponse(cached)

    if "arxiv.org" in url:
        return await _parse_arxiv_article(url, cache_key)

    try:
        raw_resp = await _http_client.get(url)
        if raw_resp.status_code in (403, 451):
            return JSONResponse({"error": "blocked", "source_url": url}, status_code=502)
        raw_html = raw_resp.text
    except Exception as e:
        return JSONResponse({"error": f"Failed to fetch article: {e}"}, status_code=502)

    title = ""
    authors: list[str] = []
    pub_date = ""
    top_image = ""
    images: list[str] = []
    text = ""

    ld = _extract_ld_json(raw_html)
    if ld and len(ld.get("text", "")) > 100:
        title     = ld["title"]
        authors   = ld["authors"]
        pub_date  = ld["publish_date"]
        top_image = ld["top_image"]
        text      = ld["text"]

    if len(text) < 100:
        try:
            loop = asyncio.get_event_loop()

            def _parse_with_trafilatura():
                extracted = trafilatura.extract(
                    raw_html,
                    url=url,
                    include_comments=False,
                    include_tables=False,
                    no_fallback=False,
                    favor_precision=True,
                )
                meta = trafilatura.extract_metadata(raw_html, default_url=url)
                return extracted or "", meta

            extracted_text, meta = await loop.run_in_executor(None, _parse_with_trafilatura)
            if len(extracted_text) > len(text):
                text = extracted_text
            if meta:
                if not title and meta.title:
                    title = meta.title
                if not authors and meta.author:
                    authors = [meta.author] if isinstance(meta.author, str) else list(meta.author)
                if not pub_date and meta.date:
                    pub_date = meta.date
                if not top_image and meta.image:
                    top_image = meta.image
        except Exception:
            pass

    if len(text.strip()) < 100:
        text = _fallback_extract_from_html(raw_html) or text

    og = _extract_og_meta(raw_html)
    if not title:
        title = og["title"]
    if not top_image:
        top_image = og["image"]
    if not pub_date:
        pub_date = og["published_time"]
    if not authors and og["author"]:
        authors = [og["author"]]

    if top_image and top_image not in images:
        images.insert(0, top_image)

    if not text or len(text.strip()) < 50:
        return JSONResponse({"error": "blocked", "source_url": url}, status_code=502)

    word_count   = len(text.split())
    reading_time = max(1, math.ceil(word_count / 200))

    result = {
        "title":        title,
        "authors":      authors,
        "publish_date": pub_date,
        "top_image":    top_image,
        "images":       images[:5],
        "text":         text,
        "source_url":   url,
        "readingTime":  reading_time,
    }
    _set_cache(cache_key, result)
    return JSONResponse(result)


async def _parse_arxiv_article(url: str, cache_key: str):
    abs_url = re.sub(r"/pdf/", "/abs/", url).split(".pdf")[0]
    try:
        resp = await _http_client.get(abs_url)
        html = resp.text

        title = ""
        m = re.search(r'<meta name="citation_title"\s+content="([^"]+)"', html)
        if m:
            title = m.group(1)

        authors = [m.group(1) for m in re.finditer(
            r'<meta name="citation_author"\s+content="([^"]+)"', html
        )]

        abstract = ""
        m = re.search(
            r'<blockquote[^>]*class="abstract[^"]*"[^>]*>\s*(?:<span[^>]*>Abstract:</span>\s*)?(.*?)</blockquote>',
            html, re.DOTALL,
        )
        if m:
            abstract = re.sub(r"<[^>]+>", "", m.group(1)).strip()

        pub_date = ""
        m = re.search(r'<meta name="citation_date"\s+content="([^"]+)"', html)
        if m:
            pub_date = m.group(1)

        word_count   = len(abstract.split())
        reading_time = max(1, math.ceil(word_count / 200))

        result = {
            "title": title, "authors": authors[:10],
            "publish_date": pub_date, "top_image": "", "images": [],
            "text": abstract, "source_url": abs_url,
            "readingTime": reading_time,
        }
        _set_cache(cache_key, result)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": f"Failed to parse arXiv article: {e}"}, status_code=502)


@app.get("/api/img")
async def api_img(url: str = Query(...)):
    """Image proxy: fetch external image, resize, serve as WebP (SSRF-protected)."""
    # SSRF check runs in executor (socket.gethostbyname is blocking)
    loop = asyncio.get_event_loop()
    safe = await loop.run_in_executor(None, lambda: _is_safe_url(url))
    if not safe:
        return Response(status_code=400)

    # Use image-appropriate headers; shared client sends text/html Accept which
    # causes some CDNs (BBC, etc.) to reject with 403.
    img_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "image/webp,image/avif,image/*,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    }
    try:
        resp = await _http_client.get(url, headers=img_headers, timeout=8.0)
        if resp.status_code in (301, 302, 303, 307, 308):
            # httpx follows redirects but log for debugging
            pass
        if resp.status_code != 200:
            return Response(status_code=404)
        content_type = resp.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            return Response(status_code=404)

        raw = resp.content
        if _ensure_pil():
            webp = await loop.run_in_executor(None, lambda: _encode_webp(raw))
            return Response(
                content=webp,
                media_type="image/webp",
                headers={"Cache-Control": "public, max-age=86400"},
            )
        # Pillow not installed: pass through original
        return Response(
            content=raw,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except Exception:
        return Response(status_code=404)


# ---------------------------------------------------------------------------
# Dev entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port  = int(os.environ.get("PORT", 5566))
    print(f"\n  The Brief — Your Morning Intelligence")
    print(f"  Open http://localhost:{port} in your browser\n")
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)

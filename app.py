#!/usr/bin/env python3
"""Daily Chore Dashboard - Personal news, stocks & search aggregator."""

import json
import math
import os
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

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
        # arXiv feeds — LLM, RL, retrieval, ranking, agents, vision, robotics
        ("arXiv CS.CL", "https://rss.arxiv.org/rss/cs.CL"),
        ("arXiv CS.AI", "https://rss.arxiv.org/rss/cs.AI"),
        ("arXiv CS.LG", "https://rss.arxiv.org/rss/cs.LG"),
        ("arXiv CS.IR", "https://rss.arxiv.org/rss/cs.IR"),
        ("arXiv CS.CV", "https://rss.arxiv.org/rss/cs.CV"),
        ("arXiv CS.RO", "https://rss.arxiv.org/rss/cs.RO"),
        ("arXiv CS.MA", "https://rss.arxiv.org/rss/cs.MA"),
        ("arXiv stat.ML", "https://rss.arxiv.org/rss/stat.ML"),
        # Frontier AI lab blogs
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
        # Google blogs
        ("Google Developers", "https://developers.googleblog.com/feeds/posts/default?alt=rss"),
        ("The Keyword Google", "https://blog.google/rss/"),
        # Expert blogs & newsletters
        ("HuggingFace", "https://huggingface.co/blog/feed.xml"),
        ("The Gradient", "https://thegradient.pub/rss/"),
        ("Lil'Log", "https://lilianweng.github.io/index.xml"),
        ("The Batch", "https://www.deeplearning.ai/the-batch/feed/"),
        ("Import AI", "https://importai.substack.com/feed"),
        ("Sebastian Raschka", "https://magazine.sebastianraschka.com/feed"),
        ("Simon Willison", "https://simonwillison.net/atom/everything/"),
        ("Chip Huyen", "https://huyenchip.com/feed.xml"),
        ("Jay Alammar", "https://jalammar.github.io/feed.xml"),
        # Community / social signal feeds
        ("r/MachineLearning", "https://www.reddit.com/r/MachineLearning/.rss"),
        ("r/LocalLLaMA", "https://www.reddit.com/r/LocalLLaMA/.rss"),
        ("HN AI", "https://hnrss.org/newest?q=LLM+OR+GPT+OR+transformer+OR+%22machine+learning%22"),
        # Conference blogs
        ("NeurIPS Blog", "https://blog.neurips.cc/feed/"),
        ("AAAI", "https://aaai.org/feed/"),
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
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
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

# Weighted keyword dict — specific/rare keywords score higher than broad ones.
# Low weights (0.5) prevent common words like "ai", "startup" from inflating scores.
HIGH_PRIORITY_KEYWORDS = {
    # India-critical (city names low weight — appear in every India story)
    "india": 1.5, "modi": 3.0, "rbi": 3.0, "sensex": 1.5, "nifty": 1.5,
    "rupee": 1.5, "parliament": 2.5, "lok sabha": 3.0, "rajya sabha": 3.0,
    "supreme court": 2.5, "delhi": 1.0, "mumbai": 1.0, "bengaluru": 1.0,
    "bangalore": 1.0, "hyderabad": 0.5, "chennai": 0.5, "kolkata": 0.5,
    "pune": 0.5, "budget": 2.5, "gdp": 2.0, "inflation": 2.0,
    "isro": 2.0, "upi": 1.5, "aadhaar": 1.0, "gst": 1.5,
    # Finance
    "market crash": 4.5, "rally": 1.0, "interest rate": 2.5, "fed": 2.0,
    "recession": 4.0, "ipo": 2.0, "stock market": 1.5, "bull": 0.5,
    "bear": 0.5, "sebi": 2.0,
    # Tech & Jobs (broad terms deliberately low to prevent inflation)
    "layoff": 3.0, "job cut": 3.5, "hiring freeze": 3.5, "wfh": 0.5,
    "remote work": 0.5, "ai": 0.5, "startup": 0.5, "unicorn": 1.5,
    "funding": 0.5,
    # Geopolitics
    "tariff": 2.0, "trade war": 4.0, "china": 1.5, "pakistan": 2.0,
    "us-india": 3.0, "sanctions": 3.0, "opec": 2.5, "oil price": 2.0,
    "climate": 1.0, "g20": 2.0, "brics": 1.5,
    # Big impact (rare = high weight)
    "breaking": 4.0, "exclusive": 1.5, "major": 0.5, "crisis": 4.0,
    "emergency": 4.5, "war": 4.0, "election": 2.5, "resignation": 3.5,
    "arrested": 2.5,
}

# Source authority — credible editorial outlets rank higher than aggregator feeds
SOURCE_AUTHORITY = {
    # Tier 1: editorial oversight, fact-checking, journalistic standards
    "BBC News": 6.0,
    "BBC Business": 6.0,
    "BBC Football": 6.0,
    "ESPN Soccer": 5.0,
    "Times of India": 5.0,
    "NDTV": 5.0,
    "Economic Times": 5.0,
    "Livemint": 4.5,
    "Moneycontrol": 4.0,
    "TechCrunch": 4.5,
    # Tier 2: aggregator feeds (content varies in quality)
    "Google News": 2.0,
    "Google News India": 2.0,
    # Tier 3: narrow-topic Google feeds (lowest editorial control)
    "Google Tech": 1.5,
    "Google Football": 1.5,
    "Google Transfer News": 1.0,
    "Google Jobs/Layoffs": 1.0,
    "Google AI News": 1.5,
    # AI lab / research blogs
    "DeepMind": 6.0,
    "Mistral": 5.0,
    "Nvidia AI": 5.0,
    "Microsoft Research": 5.0,
}

# Hard-news action verbs in title — something actually HAPPENED (not just discussed)
_HARD_NEWS_VERB_RE = re.compile(
    r'\b(?:signs?|signed|passes?|passed|announces?|announced|cuts?|raises?|hikes?|'
    r'bans?|banning|arrests?|arrested|resigns?|resigned|fires?|fired|sacks?|sacked|'
    r'orders?|launches?|launched|declares?|declared|wins?|defeats?|attacks?|invaded|'
    r'crashes?|collapsed|defaults?|sanctions?|indicts?|convicted|sentenced|suspended|'
    r'impeached|ousted|dismissed|cancels?|cancelled|approves?|approved|rejects?|rejected|'
    r'kills?|killed|dies|died|explodes?|exploded|strikes?|struck|seizes?|seized)\b',
    re.IGNORECASE,
)

# Compiled regex for soft-news / noise detection (titles only)
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
    # Analysis/explainer formats not tagged explicitly
    r'|\ball\s+about\s+(?:the|how|why|what)\b'
    r'|\bwhy\s+(?:is|are|did|does|the|india|pakistan|china|us|iran)\b'
    r'|\bhow\s+(?:\w+\s+){1,3}(?:is|are)\s+(?:driving|reshaping|affecting|impacting|changing|redefining)\b'
    r'|\bwhat\s+(?:it\s+means|you\s+should|this\s+means|experts\s+say|the\s+data)\b'
    r'|\bwhat\s+\w+\s+must\s+do\b'
    r'|\bwhat\s+to\s+(?:look\s+out|expect|know|watch)\b'
    r'|\bfiscal\s+math\b',
    re.IGNORECASE,
)

# LIVE blog/update articles — constantly-updating but less useful as discrete news
_LIVE_BLOG_RE = re.compile(
    r'\blive\s*(?:updates?|blog|ticker|news|coverage)\s*[:\-]?'
    r'|\blive\s*:\s'
    r'|\bday\s+\d+\s+live\b'
    r'|\bfollowing\s+live\b',
    re.IGNORECASE,
)

# Compiled regex for numeric magnitude (scale of real-world impact)
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

# Breaking/urgency signals — used by editors only for genuinely major stories.
# "live updates" / "live:" deliberately excluded: they're chronic live-blog markers,
# not one-time breaking news; they get their own penalty in _LIVE_BLOG_RE.
BREAKING_SIGNALS = [
    "breaking", "breaking news", "just in", "urgent", "alert", "developing",
    "flash:", "exclusive:", "at this hour",
]

# High-impact importance signals — scale, severity, historic nature
IMPORTANCE_SIGNALS = [
    # Historic/unprecedented
    "record high", "record low", "all-time high", "all-time low", "historic",
    "landmark", "unprecedented", "first ever", "first time in history",
    # Catastrophic events
    "catastrophic", "devastating", "collapse", "explosion", "blast",
    "earthquake", "floods", "disaster",
    # Casualties / human impact
    "killed", "dead", "casualties", "death toll", "fatalities", "wounded",
    "missing", "plane crash", "train crash",
    # Major decisions / legal
    "arrested", "indicted", "convicted", "sentenced", "ban", "banned",
    "parliament passes", "bill passed", "supreme court rules", "court orders",
    "declares emergency", "emergency declared", "martial law",
    # Economic scale
    "billion dollar", "trillion", "market crash", "stock market crash",
    "currency crisis", "debt default", "bankruptcy", "bank collapse",
    # Political shocks
    "resignation", "resigned", "ousted", "coup", "impeached", "fired",
    "invasion", "attack", "war declared", "ceasefire declared",
]

# Football match outcome detection — distinguishes results from previews.
# Use past/completed forms only: "wins" (3rd person result), not "win" (infinitive preview).
# "beat X 2-0" = result; "must beat X" = preview — avoid infinitive forms.
_FOOTBALL_OUTCOME_RE = re.compile(
    r'\b(?:\d\s*[-–]\s*\d|wins\b|win\s+\d|loses?\b|beaten\b|'
    r'victory\b|defeats?\b|thrash(?:es)?\b|hammer(?:s)?\b|demolish(?:es)?\b|'
    r'knocked\s+out\b|eliminat(?:ed|es)\b|relegated\b|promoted\b|'
    r'champions\b|title\s+winner|final\s+score|full[- ]time|ft:|'
    r'hat[- ]trick|brace\b|own\s+goal|penalty\s+shootout|extra\s+time)\b',
    re.IGNORECASE,
)

# Major competitions — presence elevates importance
_FOOTBALL_COMPETITIONS_RE = re.compile(
    r'\b(?:premier\s+league|champions\s+league|la\s+liga|bundesliga|serie\s+a|'
    r'ligue\s+1|europa\s+league|conference\s+league|fa\s+cup|carabao\s+cup|'
    r'world\s+cup|euro\s+20\d{2}|copa\s+america|supercopa|dfb[- ]pokal|'
    r'community\s+shield|isl|afc\s+champions)\b',
    re.IGNORECASE,
)

# Football-specific importance signals
FOOTBALL_IMPORTANCE_SIGNALS = [
    # High-stakes competitions
    "champions league", "world cup", "euro 2024", "euro 2025", "euro 2026",
    "copa america", "europa league", "fa cup", "carabao cup", "community shield",
    "conference league", "supercopa", "dfb-pokal",
    # Stage of competition
    "final", "semi-final", "semifinal", "quarter-final", "quarterfinal",
    "knockout stage", "round of 16", "last 16", "last 8", "group stage",
    # Decisive outcomes
    "wins title", "crowned champions", "lifts the trophy", "relegated",
    "promotion", "promoted", "qualifies", "qualification", "advances",
    "knocked out", "eliminat", "title race", "title decider",
    # Big match events
    "hat-trick", "brace", "red card", "penalty shootout", "extra time",
    "comeback", "comeback victory", "thriller", "stunner", "upset",
    "derby", "el clasico", "north west derby", "merseyside derby",
    # Transfer news
    "record transfer", "world record", "transfer confirmed", "officially signs",
    "unveiled", "done deal", "departure confirmed", "free agent signs",
    # Managerial
    "sacked", "appointed manager", "new manager", "manager resigns",
    "interim manager",
    # Player news
    "injured", "ruled out", "long-term injury", "suspended", "banned",
    "returns from injury", "retirement announced", "retires",
]

# AI/ML weighted keyword dict — specific/rare terms score far higher than broad ones.
# Weights represent editorial signal strength: frontier model names score highest,
# generic terms like "ai" very low to prevent inflation.
AI_HIGH_IMPACT_KEYWORDS = {
    # Frontier model names — very high signal, almost always newsworthy
    "gpt-5": 8.0, "gpt-4o": 5.0, "o3": 6.0, "o4": 7.0,
    "claude 4": 8.0, "claude 3.7": 6.0, "claude 3.5": 5.0,
    "gemini 2.0": 6.0, "gemini ultra": 6.0, "gemini 2.5": 7.0,
    "llama 4": 7.0, "llama 3": 4.0,
    "deepseek r2": 7.0, "deepseek v3": 6.0, "deepseek r1": 5.0,
    "grok 3": 6.0, "grok 2": 4.0,
    "mistral large": 5.0, "mistral small": 3.0,
    # High-impact techniques / milestones
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
    # Moderate signal — important but very common in arXiv papers
    "reinforcement learning": 1.5, "large language model": 1.0,
    "open source": 1.5, "open-source": 1.5,
    "llm": 0.8, "gpt": 1.5, "transformer": 0.8, "attention mechanism": 1.5,
    # Common arXiv paper topics — low weight to prevent inflation
    "agent": 0.8, "embedding": 0.5, "retrieval": 0.5,
    "rag": 0.8, "retrieval augmented": 1.2, "vector search": 1.0,
    "multi-agent": 1.5, "benchmark": 0.8,
    # Very broad terms (very low weight)
    "neural network": 0.3, "machine learning": 0.3, "deep learning": 0.3,
    "ai": 0.2, "artificial intelligence": 0.3, "ml": 0.2,
}

# Source authority tiers for AI articles — lab blogs >> expert >> arXiv >> aggregator
AI_SOURCE_TIERS = {
    # Tier 1: frontier labs — primary source of groundbreaking work
    "OpenAI": 8.0, "Anthropic": 8.0, "DeepMind": 8.0,
    "Google AI": 7.0, "Meta AI": 7.0, "Mistral": 6.0, "Nvidia AI": 6.0,
    "Microsoft Research": 6.0, "Apple ML": 6.5, "Amazon Science": 5.5,
    "Together AI": 4.5,
    # Tier 2: high-quality expert blogs & newsletters
    "Lil'Log": 6.0, "The Gradient": 5.0, "HuggingFace": 5.0,
    "The Batch": 5.0, "Import AI": 5.0, "Sebastian Raschka": 5.0,
    "Simon Willison": 4.5, "Chip Huyen": 5.0, "Jay Alammar": 4.5,
    # Tier 2b: Google blogs
    "Google Developers": 3.5, "The Keyword Google": 3.0,
    # Tier 2c: conference blogs
    "NeurIPS Blog": 6.0, "AAAI": 5.0,
    # Tier 3: arXiv (high volume, variable quality)
    "arXiv CS.CL": 2.0, "arXiv CS.AI": 2.0, "arXiv CS.LG": 2.0, "arXiv CS.IR": 1.5,
    "arXiv CS.CV": 2.0, "arXiv CS.RO": 1.5, "arXiv CS.MA": 1.5, "arXiv stat.ML": 1.5,
    # Tier 4: community / aggregated (social signal, not editorial)
    "r/MachineLearning": 2.5, "r/LocalLLaMA": 2.0, "HN AI": 2.5,
    "Google AI News": 1.5,
    # Tier 0: HuggingFace Daily Papers (curated trending — very high signal)
    "HF Daily Papers": 7.0,
}

# SOTA / breakthrough detection — something genuinely novel happened
_AI_SOTA_RE = re.compile(
    r'\b(?:state[- ]of[- ]the[- ]art|sota|outperforms?|surpasses?|'
    r'beats?\s+(?:gpt|claude|gemini|llama)|new\s+record|best[- ]in[- ]class|'
    r'first\s+to\s+achieve|breakthrough|game[- ]changing|unprecedented\s+performance)\b',
    re.IGNORECASE,
)

# Novel work signals — paper/model introduction vs discussion
_AI_NOVEL_RE = re.compile(
    r'\b(?:we\s+(?:introduce|present|propose)|introducing\b|novel\s+approach|'
    r'new\s+(?:method|framework|model|architecture)|(?:releases?|released|open[- ]source[sd])\b)\b',
    re.IGNORECASE,
)

# Noise / low-value content — roundups, tutorials, getting-started guides
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


def _title_fingerprint(title: str) -> frozenset:
    """Extract key content words from title for cross-source story clustering.

    Strips trailing source attributions (e.g. '| India News', '| Hindustan Times')
    that RSS feeds append — these inflate the fingerprint with outlet-specific noise
    and lower the overlap ratio between articles covering the same story.
    """
    STOP = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "to", "of",
        "in", "on", "at", "for", "with", "by", "from", "and", "or", "but", "not",
        "as", "it", "its", "he", "she", "they", "we", "i", "this", "that", "which",
        "who", "has", "have", "had", "will", "would", "could", "should", "after",
        "before", "over", "under", "up", "down", "says", "said", "says",
        # Outlet noise words that appear in RSS title suffixes
        "news", "times", "post", "herald", "tribune", "express", "live", "today",
        "india", "daily", "online",
    }
    # Strip trailing source attributions added by feeds: " | India News", " | Hindustan Times"
    clean = re.sub(r'\s*\|\s*.+$', '', title)
    words = re.findall(r'\b[a-z]+\b', clean.lower())
    return frozenset(w for w in words if w not in STOP and len(w) > 2)


def _score_article(item: dict) -> float:
    """Score article importance using multiplicative recency.

    Formula: max(importance, 0) * recency_multiplier + source_authority

    This ensures recency amplifies importance rather than replacing it —
    a trivial recent article cannot outscore a genuinely important older one.
    """
    title = item.get("title", "").lower()
    desc  = item.get("description", "").lower()
    pub   = item.get("published", "")
    importance = 0.0

    # Keywords: title match = 3× weight (headline is the primary editorial signal).
    # A keyword in a title means the article IS about that topic.
    # In description it might just be context.
    for kw, weight in HIGH_PRIORITY_KEYWORDS.items():
        if kw in title:
            importance += weight * 3.0
        elif kw in desc:
            importance += weight * 0.8

    # Breaking/urgency — editors only use these labels for genuinely major events
    for kw in BREAKING_SIGNALS:
        if kw in title:
            importance += 10.0
            break

    # High-impact event signals — title match worth much more than description.
    # "record high/low" separated: it fires too broadly (UK school attendance, stock records)
    # and shouldn't score the same as plane crashes or market collapses.
    BROAD_RECORD_SIGNALS = {"record high", "record low", "all-time high", "all-time low"}
    for kw in IMPORTANCE_SIGNALS:
        if kw in title:
            importance += 4.0 if kw in BROAD_RECORD_SIGNALS else 8.0
        elif kw in desc:
            importance += 1.5 if kw in BROAD_RECORD_SIGNALS else 3.0

    # Hard-news action verb in title: something actually HAPPENED
    if _HARD_NEWS_VERB_RE.search(title):
        importance += 6.0

    # Numeric magnitude — real-world scale in the headline
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

    # Soft-news / analysis penalty — drags importance below 0 so recency can't rescue it
    if _SOFT_NEWS_RE.search(title):
        importance -= 20.0

    # LIVE blog penalty: live-blogs are constantly updated aggregations, not discrete news.
    # Strong penalty so they rank well below individual news reports of the same story.
    if _LIVE_BLOG_RE.search(title):
        importance -= 15.0

    # Hyperlocal foreign penalty
    text = title + " " + desc
    local_foreign = [
        "county", "sheriff", "township", "borough", "precinct", "school board",
        "state trooper", "local police", "neighborhood",
    ]
    if any(lf in text for lf in local_foreign) and "india" not in text:
        importance -= 25.0

    # Recency: exponential decay with configurable half-life.
    # Breaking news decays with ~3hr half-life; non-breaking uses importance only.
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
            # Exponential decay: half-life ~3 hours, max 2.5x for very fresh
            recency_mult = 2.5 * math.exp(-0.23 * max(age_h, 0))
            recency_mult = max(recency_mult, 0.5)
    else:
        recency_mult = 1.0  # flat — rank by importance only

    source_boost = SOURCE_AUTHORITY.get(item.get("source", ""), 1.5)
    return max(importance, 0.0) * recency_mult + source_boost


def _score_football_article(item: dict) -> float:
    """Score football article using multiplicative recency (72-hr window).

    Formula: max(importance, 0) * recency_multiplier + source_authority

    Key design choices:
    - Recency multipliers deliberately low (max 1.3) so that a genuinely
      important older result is never buried by a trivial fresh preview.
    - Outcome amplifier: competition + confirmed result × 2.5 importance.
      A CL final result from 36h ago should always beat a CL preview from 1h ago.
    """
    title = item.get("title", "").lower()
    desc  = item.get("description", "").lower()
    pub   = item.get("published", "")
    importance = 0.0

    # Football importance signals — title match worth far more than description
    for kw in FOOTBALL_IMPORTANCE_SIGNALS:
        if kw in title:
            importance += 10.0
        elif kw in desc:
            importance += 4.0

    for kw in BREAKING_SIGNALS:
        if kw in title:
            importance += 10.0
            break

    # Transfer fee / prize money magnitude
    if _BIG_MONEY_RE.search(title):
        importance += 12.0
    elif _BIG_MONEY_RE.search(desc):
        importance += 5.0

    # Outcome amplifier: article confirmed a match result in a major competition.
    # A result article is always more important than a preview of the same match.
    has_outcome = bool(_FOOTBALL_OUTCOME_RE.search(title))
    has_competition = bool(_FOOTBALL_COMPETITIONS_RE.search(title) or _FOOTBALL_COMPETITIONS_RE.search(desc))
    if has_outcome and has_competition:
        importance *= 2.5
    elif has_outcome:
        importance *= 1.5

    # Soft-news penalty (previews, opinion, listicles)
    if _SOFT_NEWS_RE.search(title):
        importance -= 20.0

    # Recency: exponential decay with ~18hr half-life. Kept deliberately gentle
    # so important older results beat trivial fresh previews. Max 1.3.
    age_h = None
    if pub:
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(pub)).total_seconds() / 3600
        except Exception:
            pass
    if age_h is None:
        recency_mult = 0.5
    else:
        recency_mult = 1.3 * math.exp(-0.039 * max(age_h, 0))  # half-life ~18h
        recency_mult = max(recency_mult, 0.1)

    source_boost = SOURCE_AUTHORITY.get(item.get("source", ""), 1.5)
    return max(importance, 0.0) * recency_mult + source_boost


def _score_ai_article(item: dict) -> float:
    """Score an AI research/blog article using multiplicative recency (3-month window).

    Formula: max(importance, 0) * recency_multiplier + source_tier

    Design:
    - Title-biased keywords (title = 3× weight) so frontier model announcements
      that lead with the model name score far above generic arXiv papers.
    - SOTA/breakthrough regex boosts breakthrough results.
    - Noise penalty collapses roundups/tutorials below the floor.
    - 3-month recency window: important older papers still surface above fresh noise.
    """
    title = item.get("title", "").lower()
    desc  = item.get("description", "").lower()
    pub   = item.get("published", "")
    source = item.get("source", "")
    importance = 0.0

    # Title-biased weighted keyword scoring.
    # Keyword importance is capped at 12 to prevent keyword-rich arXiv titles
    # from dominating; SOTA/novel signals (below) push past the cap.
    kw_importance = 0.0
    for kw, weight in AI_HIGH_IMPACT_KEYWORDS.items():
        if kw in title:
            kw_importance += weight * 3.0
        elif kw in desc:
            kw_importance += weight * 0.8
    importance += min(kw_importance, 12.0)

    # SOTA / breakthrough detection
    if _AI_SOTA_RE.search(title):
        importance += 8.0
    elif _AI_SOTA_RE.search(desc):
        importance += 3.0

    # Novel work (paper/model release) — "we introduce / releasing / open-sourced"
    if _AI_NOVEL_RE.search(title):
        importance += 5.0

    # arXiv papers without any SOTA or novel signal are likely routine submissions.
    # Apply a penalty so they don't rank above genuine announcements.
    is_arxiv = source.startswith("arXiv")
    has_signal = _AI_SOTA_RE.search(title) or _AI_NOVEL_RE.search(title)
    if is_arxiv and not has_signal:
        importance -= 6.0

    # Noise penalty — roundups, tutorials, getting-started guides
    if _AI_NOISE_RE.search(title):
        importance -= 15.0
    if _SOFT_NEWS_RE.search(title):
        importance -= 10.0

    # Recency: exponential decay with ~48hr half-life.
    # Max 2.0 so a breakthrough from last week still beats fresh trivia.
    age_h = None
    if pub:
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(pub)).total_seconds() / 3600
        except Exception:
            pass
    if age_h is None:
        recency_mult = 0.5
    else:
        recency_mult = 2.0 * math.exp(-0.0145 * max(age_h, 0))  # half-life ~48h
        recency_mult = max(recency_mult, 0.1)

    source_boost = AI_SOURCE_TIERS.get(item.get("source", ""), 1.5)
    return max(importance, 0.0) * recency_mult + source_boost


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

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_fetch_feed, name, url): name for name, url in feeds}
        # For AI research, also pull in HuggingFace Daily Papers as a high-signal source
        hf_future = None
        if category == "ai_research":
            hf_future = pool.submit(_fetch_hf_daily_papers)
        for future in as_completed(futures):
            try:
                all_items.extend(future.result())
            except Exception:
                pass
        if hf_future:
            try:
                hf_papers = hf_future.result()
                for p in hf_papers:
                    p["source"] = "HF Daily Papers"
                all_items.extend(hf_papers)
            except Exception:
                pass

    # Build cross-source fingerprints + source names for multi-outlet detection
    all_fingerprints = [_title_fingerprint(item["title"]) for item in all_items]
    all_sources      = [item.get("source", "") for item in all_items]

    # Deduplicate by title similarity
    seen_titles: set[str] = set()
    unique: list[dict] = []
    unique_indices: list[int] = []  # track original indices for cross-source lookup
    is_ai = category == "ai_research"
    is_football = category == "football"
    for idx, item in enumerate(all_items):
        key = re.sub(r"\W+", "", item["title"].lower())[:50]
        if key not in seen_titles:
            seen_titles.add(key)
            if is_ai:
                item["tag"] = _tag_ai_article(item)
                item["score"] = _score_ai_article(item)
            elif is_football:
                item["tag"] = _tag_article(item)
                item["score"] = _score_football_article(item)
            else:
                item["tag"] = _tag_article(item)
                item["score"] = _score_article(item)
            # Store fingerprint on item so diversity pass stays correct after sorting
            item["_fp"] = all_fingerprints[idx]
            unique.append(item)
            unique_indices.append(idx)

    # Cross-source boost: stories covered by DIFFERENT outlets are more important.
    # Same-feed duplicates are excluded so the signal reflects true editorial consensus.
    # For AI: collapse all arXiv sub-feeds into one logical source so cross-category
    # arXiv papers don't falsely boost each other (they're the same publisher).
    def _cross_source_name(src: str) -> str:
        return "arXiv" if src.startswith("arXiv") else src

    for i, item in enumerate(unique):
        fp          = all_fingerprints[unique_indices[i]]
        item_source = _cross_source_name(all_sources[unique_indices[i]])
        if len(fp) < 2:
            continue
        seen_cross_sources: set[str] = set()
        for j, (other_fp, other_src) in enumerate(zip(all_fingerprints, all_sources)):
            norm_src = _cross_source_name(other_src)
            if (j != unique_indices[i]
                    and norm_src != item_source          # must be a different outlet
                    and norm_src not in seen_cross_sources
                    and len(other_fp) > 0
                    # 0.45 threshold requires specific story overlap, not just shared topic words.
                    # Lower threshold (0.35) caused broad-topic tech articles ("apple security")
                    # to falsely amplify each other across many outlets.
                    and len(fp & other_fp) / max(len(fp), len(other_fp)) >= 0.45):
                seen_cross_sources.add(norm_src)
        cross_count = len(seen_cross_sources)
        if cross_count > 0:
            # Cap at 12: multi-outlet coverage is important but shouldn't dominate over
            # genuine importance score. 3.0/outlet means 4 outlets = +12, the max.
            boost = min(cross_count * 3.0, 12.0)
            item["score"] = item.get("score", 0) + boost

    # Sort by score descending — pure importance ranking, no recency bucket guarantee.
    unique.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Topic-diversity pass for top_news: cap same-topic articles at 3 per cluster
    # so a single event (e.g. Iran war) doesn't consume the entire top-20.
    # Fingerprints are stored on items so the pass stays correct after sorting.
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
                    overlap = len(fp & cfp) / max(len(fp), len(cfp))
                    if overlap >= 0.50:
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

    limit = 50
    result = unique[:limit]
    # Strip internal _fp (frozenset) — not JSON serializable and not needed by the API
    for item in result:
        item.pop("_fp", None)
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
    start = now - timedelta(days=7)
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
# Trending Papers — HuggingFace Daily Papers + community signals
# ---------------------------------------------------------------------------

def _fetch_hf_daily_papers() -> list[dict]:
    """Fetch trending papers from HuggingFace Daily Papers API."""
    try:
        resp = requests.get("https://huggingface.co/api/daily_papers", headers=HEADERS, timeout=12)
        if resp.status_code != 200:
            return []
        papers = resp.json()
        items = []
        for p in papers[:30]:
            paper = p.get("paper", {})
            title = paper.get("title", "")
            abstract = paper.get("summary", "")
            arxiv_id = paper.get("id", "")
            pub_date = paper.get("publishedAt", "")
            upvotes = p.get("numUpvotes", 0)
            if not title:
                continue
            items.append({
                "title": title,
                "link": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
                "source": "HF Daily Papers",
                "published": pub_date,
                "description": (abstract[:220] + "...") if len(abstract) > 220 else abstract,
                "thumbnail": "",
                "upvotes": upvotes,
                "paper_id": arxiv_id,
            })
        return items
    except Exception:
        return []


def _fetch_hf_trending_models() -> list[dict]:
    """Fetch popular models from HuggingFace API."""
    try:
        resp = requests.get(
            "https://huggingface.co/api/models",
            params={"sort": "likes", "direction": "-1", "limit": "15"},
            headers=HEADERS, timeout=10,
        )
        if resp.status_code != 200:
            return []
        models = resp.json()
        items = []
        for m in models:
            model_id = m.get("modelId", "") or m.get("id", "")
            tags = m.get("tags", [])
            pipeline = m.get("pipeline_tag", "")
            likes = m.get("likes", 0)
            downloads = m.get("downloads", 0)
            items.append({
                "model_id": model_id,
                "pipeline": pipeline,
                "tags": tags[:5],
                "likes": likes,
                "downloads": downloads,
                "link": f"https://huggingface.co/{model_id}",
            })
        return items
    except Exception:
        return []


def _fetch_trending() -> dict:
    """Fetch all trending data: daily papers + trending models."""
    cached = _cached("trending_data", ttl=600)
    if cached is not None:
        return cached

    papers = []
    models = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        fp = pool.submit(_fetch_hf_daily_papers)
        fm = pool.submit(_fetch_hf_trending_models)
        try:
            papers = fp.result()
        except Exception:
            pass
        try:
            models = fm.result()
        except Exception:
            pass

    # Score and tag the daily papers using the AI scoring pipeline
    for item in papers:
        item["tag"] = _tag_ai_article(item)
        item["score"] = _score_ai_article(item)
        # Boost by community upvotes (log scale to prevent runaway)
        upvotes = item.get("upvotes", 0)
        if upvotes > 0:
            item["score"] += min(math.log2(upvotes + 1) * 2.0, 10.0)

    papers.sort(key=lambda x: x.get("score", 0), reverse=True)

    result = {"papers": papers, "models": models}
    _set_cache("trending_data", result)
    return result


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


@app.route("/api/trending")
def api_trending():
    """Return trending papers and models from HuggingFace."""
    return jsonify(_fetch_trending())


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

    # Boxscore stats — ESPN API key → friendly display label
    STAT_KEYS = {
        "Possession":       "Possession",
        "SHOTS":            "Total Shots",
        "ON GOAL":          "Shots on Target",
        "Corner Kicks":     "Corner Kicks",
        "Fouls":            "Fouls",
        "Yellow Cards":     "Yellow Cards",
        "Red Cards":        "Red Cards",
        "Offsides":         "Offsides",
        "Saves":            "Saves",
        "Pass Completion %":"Pass Completion %",
        "Accurate Passes":  "Accurate Passes",
    }
    team_stats = []
    for t in sdata.get("boxscore", {}).get("teams", []):
        stat_map = {s["label"]: s["displayValue"] for s in t.get("statistics", [])}
        team_stats.append({
            "name": t.get("team", {}).get("displayName", "?"),
            "stats": {display: stat_map.get(api_key, "-") for api_key, display in STAT_KEYS.items()},
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


def _extract_ld_json(html: str) -> dict | None:
    """Extract article data from LD+JSON structured data embedded in HTML."""
    ld_blocks = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    for block in ld_blocks:
        try:
            data = json.loads(block)
            # Handle @graph arrays
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                atype = item.get("@type", "")
                if atype in ("NewsArticle", "Article", "ReportageNewsArticle",
                             "WebPage") or "Article" in str(atype):
                    body = item.get("articleBody", "")
                    if body and len(body) > 100:
                        # Extract structured fields
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

                        pub = item.get("datePublished", "")

                        return {
                            "title": item.get("headline", ""),
                            "authors": [a for a in authors if a],
                            "publish_date": pub,
                            "top_image": img,
                            "text": body,
                        }
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _extract_og_meta(html: str) -> dict:
    """Extract Open Graph / meta tag fallback info."""
    def _meta(prop):
        m = re.search(
            rf'<meta[^>]*(?:property|name)=["\'](?:og:)?{prop}["\'][^>]*content=["\']([^"\']+)',
            html, re.I,
        )
        return m.group(1) if m else ""
    return {
        "title": _meta("title"),
        "description": _meta("description"),
        "image": _meta("image"),
        "author": _meta("author"),
        "published_time": _meta("article:published_time"),
    }


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

    # Special handling for arXiv
    if "arxiv.org" in url:
        return _parse_arxiv_article(url, cache_key)

    try:
        # First, fetch the raw HTML ourselves for LD+JSON / meta extraction
        raw_resp = requests.get(url, headers=HEADERS, timeout=12)

        # Some sites (NDTV, etc.) block server-side requests
        if raw_resp.status_code in (403, 451):
            return jsonify({"error": "blocked", "source_url": url}), 502

        raw_html = raw_resp.text

        title = ""
        authors: list[str] = []
        pub_date = ""
        top_image = ""
        images: list[str] = []
        text = ""

        # Strategy 1: LD+JSON structured data (most reliable for modern sites)
        ld = _extract_ld_json(raw_html)
        if ld and len(ld.get("text", "")) > 100:
            title = ld["title"]
            authors = ld["authors"]
            pub_date = ld["publish_date"]
            top_image = ld["top_image"]
            text = ld["text"]

        # Strategy 2: newspaper4k (good general parser)
        if len(text) < 100:
            try:
                article = Article(url, headers=HEADERS)
                article.html = raw_html
                article.parse()
                if len(article.text or "") > len(text):
                    text = article.text
                if not title:
                    title = article.title or ""
                if not authors and article.authors:
                    authors = article.authors
                if not pub_date and article.publish_date:
                    pub_date = article.publish_date.isoformat()
                if not top_image:
                    top_image = article.top_image or ""
                for img in article.images:
                    if img not in images and img != top_image:
                        images.append(img)
                    if len(images) >= 4:
                        break
            except Exception:
                pass

        # Strategy 3: Regex fallback for <article>/<p> extraction
        if len(text.strip()) < 100:
            text = _fallback_extract_from_html(raw_html) or text

        # Fill missing metadata from OG meta tags
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
            return jsonify({"error": "blocked", "source_url": url}), 502

        result = {
            "title": title,
            "authors": authors,
            "publish_date": pub_date,
            "top_image": top_image,
            "images": images[:5],
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


def _fallback_extract_from_html(html: str) -> str:
    """Fallback text extraction using regex on pre-fetched HTML."""
    try:
        # Try to find <article> tag content
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

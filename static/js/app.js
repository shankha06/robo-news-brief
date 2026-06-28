/* =========================================================================
   The Brief — Frontend v3.0
   Features: SSE streaming, dark mode, bookmarks, keyboard nav, trending,
   dynamic columns, article search, reading list, image proxy, PWA
   ========================================================================= */

(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);

  // ── Helpers ──────────────────────────────────────────────────────────
  function timeAgo(iso) {
    if (!iso) return "";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  }

  function fmtPrice(p, cur) {
    if (cur === "INR") return "\u20B9" + p.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return "$" + p.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function fmtPct(pct) {
    const s = pct >= 0 ? "+" : "";
    return `${s}${pct.toFixed(2)}%`;
  }

  function tagClass(tag) { return `tag-${tag || "General"}`; }

  /** Route external image URLs through the server-side proxy (WebP + SSRF safe). */
  function proxyImg(url) {
    if (!url || url.startsWith("data:") || url.startsWith("/api/img")) return url;
    return `/api/img?url=${encodeURIComponent(url)}`;
  }

  // ── Dark Mode ─────────────────────────────────────────────────────────
  const themeToggle = $("#themeToggle");
  function applyTheme(dark) {
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    localStorage.setItem("theme", dark ? "dark" : "light");
  }
  const savedTheme = localStorage.getItem("theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(savedTheme ? savedTheme === "dark" : prefersDark);

  themeToggle.addEventListener("click", () => {
    applyTheme(document.documentElement.getAttribute("data-theme") !== "dark");
  });

  // ── Header ────────────────────────────────────────────────────────────
  (function initHeader() {
    const d = new Date();
    const el = $("#currentDate");
    if (el) el.textContent = d.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "short", year: "numeric" });
    const h = d.getHours();
    let edition = "Morning Edition";
    if (h >= 12 && h < 17) edition = "Afternoon Edition";
    else if (h >= 17) edition = "Evening Edition";
    const edEl = $("#editionLabel");
    if (edEl) edEl.textContent = edition;
  })();

  function stampUpdate() {
    const el = $("#lastUpdated");
    if (el) el.textContent = new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
  }

  // ── Search ────────────────────────────────────────────────────────────
  // Search bar is Google-only. Typing does nothing locally; Enter/submit
  // opens Google in a new tab via the form's method="get" action.
  const searchInput = $("#searchInput");

  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      searchInput.value = "";
      searchInput.blur();
    }
    // Enter: form submits naturally to Google — no local filtering
  });

  // ── Bookmarks ──────────────────────────────────────────────────────────
  let bookmarks = JSON.parse(localStorage.getItem("bookmarks") || "[]");

  function saveBookmarks() {
    localStorage.setItem("bookmarks", JSON.stringify(bookmarks));
    updateBookmarkCount();
  }

  function updateBookmarkCount() {
    const el = $("#bookmarkCount");
    if (bookmarks.length > 0) {
      el.style.display = "inline";
      el.textContent = bookmarks.length;
    } else {
      el.style.display = "none";
    }
  }

  function isBookmarked(url) { return bookmarks.some(b => b.url === url); }

  function toggleBookmark(item) {
    const idx = bookmarks.findIndex(b => b.url === item.link);
    if (idx >= 0) {
      bookmarks.splice(idx, 1);
    } else {
      bookmarks.push({ url: item.link, title: item.title, source: item.source, tag: item.tag, savedAt: new Date().toISOString() });
    }
    saveBookmarks();
    renderBookmarks();
  }

  function renderBookmarks() {
    const body = $("#bookmarksBody");
    if (!bookmarks.length) {
      body.innerHTML = `<div class="bookmarks-empty">No bookmarks yet. Press <kbd>s</kbd> on any article to save it.</div>`;
      return;
    }
    body.innerHTML = bookmarks.map((b, i) => `
      <div class="bookmark-item">
        <a href="${b.url}" target="_blank" rel="noopener" class="bookmark-link">
          <span class="news-tag ${tagClass(b.tag)}">${b.tag || "General"}</span>
          <span class="bookmark-title">${b.title}</span>
          <span class="bookmark-meta">${b.source} &middot; ${timeAgo(b.savedAt)}</span>
        </a>
        <button class="bookmark-remove" data-idx="${i}" title="Remove">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
    `).join("");
  }

  const bookmarksPanel = $("#bookmarksPanel");
  $("#bookmarksToggle").addEventListener("click", () => {
    bookmarksPanel.classList.toggle("open");
    if (bookmarksPanel.classList.contains("open")) renderBookmarks();
  });
  $("#bookmarksClose").addEventListener("click", () => bookmarksPanel.classList.remove("open"));
  bookmarksPanel.addEventListener("click", (e) => {
    const rm = e.target.closest(".bookmark-remove");
    if (rm) {
      bookmarks.splice(parseInt(rm.dataset.idx), 1);
      saveBookmarks();
      renderBookmarks();
    }
  });

  updateBookmarkCount();

  // ── Column count helper ───────────────────────────────────────────────
  function updateColCount(id, count) {
    const el = $(`#${id}`);
    if (el) el.textContent = count > 0 ? `(${count})` : "";
  }

  // ── Dynamic Column Sizing ─────────────────────────────────────────────
  function adjustColumns(newsCount, footballCount, aiCount) {
    const grid = $("#gridMain");
    if (!grid) return;
    const total = newsCount + footballCount + aiCount;
    if (total === 0) return;
    const newsRatio     = Math.max(0.25, Math.min(0.45, newsCount / total));
    const footballRatio = Math.max(0.2,  Math.min(0.35, footballCount / total));
    const aiRatio       = Math.max(0.25, Math.min(0.45, aiCount / total));
    const sum = newsRatio + footballRatio + aiRatio;
    if (window.innerWidth > 1200) {
      grid.style.gridTemplateColumns = `${newsRatio/sum}fr ${footballRatio/sum}fr ${aiRatio/sum}fr`;
    }
  }

  // ── News Rendering ────────────────────────────────────────────────────
  let allTopNews = [];

  function heroCard(item) {
    const bm = isBookmarked(item.link) ? " bookmarked" : "";
    return `<a href="${item.link}" target="_blank" rel="noopener" class="news-hero${bm}" data-url="${item.link}">
      <span class="hero-tag news-tag ${tagClass(item.tag)}">${item.tag}</span>
      <h3 class="hero-title">${item.title}</h3>
      <p class="hero-desc">${item.description || ""}</p>
      <div class="hero-meta">
        <span class="hero-source">${item.source}</span>
        <span class="hero-time">${timeAgo(item.published)}</span>
      </div>
    </a>`;
  }

  function newsRow(item) {
    const thumb = item.thumbnail
      ? `<img class="news-row-thumb" src="${proxyImg(item.thumbnail)}" alt="" loading="lazy" onerror="this.style.display='none'">`
      : "";
    const bm = isBookmarked(item.link) ? " bookmarked" : "";
    return `<a href="${item.link}" target="_blank" rel="noopener" class="news-row${bm}" data-url="${item.link}">
      ${thumb}
      <div class="news-row-body">
        <div class="news-row-head">
          <span class="news-tag ${tagClass(item.tag)}">${item.tag}</span>
        </div>
        <div class="news-row-title">${item.title}</div>
        <div class="news-row-meta">
          <span class="news-row-source">${item.source}</span>
          <span class="news-row-time">${timeAgo(item.published)}</span>
        </div>
      </div>
    </a>`;
  }

  function renderNews(container, items, showHero = false) {
    if (!items.length) {
      container.innerHTML = `<div class="error-state">No articles found.</div>`;
      return;
    }
    let html = "";
    const start = showHero ? 1 : 0;
    if (showHero) html += heroCard(items[0]);
    for (let i = start; i < items.length; i++) html += newsRow(items[i]);
    container.innerHTML = html;
  }

  // ── SSE-based news loading ────────────────────────────────────────────
  let _newsSources = {};

  /**
   * Open an SSE stream for a feed category.
   * Renders partial results as data events arrive; closes on "done".
   */
  function subscribeNews(cat, containerId, onItems) {
    if (_newsSources[cat]) {
      _newsSources[cat].close();
      delete _newsSources[cat];
    }
    const c = $(containerId);

    const src = new EventSource(`/api/news/stream/${cat}`);
    _newsSources[cat] = src;

    src.onmessage = (e) => {
      try {
        const items = JSON.parse(e.data);
        if (Array.isArray(items) && items.length > 0) {
          onItems(items, c);
        }
      } catch (_) {}
    };

    src.addEventListener("done", () => {
      src.close();
      delete _newsSources[cat];
    });

    src.onerror = () => {
      src.close();
      delete _newsSources[cat];
      if (!c.querySelector(".news-hero, .news-row, .ai-card")) {
        c.innerHTML = `<div class="error-state">Failed to load. Try refreshing.</div>`;
      }
    };

    return src;
  }

  function loadTopNews() {
    return subscribeNews("top_news", "#topNewsContainer", (items, c) => {
      allTopNews = items;
      renderNews(c, items, true);
      updateColCount("newsCount", items.length);
    });
  }

  function loadFootball() {
    let footballItems = [];
    return subscribeNews("football", "#footballContainer", (items, c) => {
      footballItems = items;
      renderNews(c, items, false);
      updateColCount("footballCount", items.length);
    });
  }

  // ── News Filters ──────────────────────────────────────────────────────
  function applyNewsFilter(tag) {
    let items = tag === "all" ? allTopNews : allTopNews.filter((i) => i.tag === tag);
    if (items.length < 3) items = allTopNews;
    renderNews($("#topNewsContainer"), items, true);
    updateColCount("newsCount", items.length);
  }

  $$("#newsFilters .pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$("#newsFilters .pill").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      applyNewsFilter(btn.dataset.filter);
    });
  });

  // ── AI Research Rendering ─────────────────────────────────────────────
  let allAiItems = [];

  function aiCard(item) {
    const bm = isBookmarked(item.link) ? " bookmarked" : "";
    const upvotes = item.upvotes ? `<span class="ai-upvotes" title="HuggingFace upvotes">${item.upvotes}</span>` : "";
    return `<a href="${item.link}" target="_blank" rel="noopener" class="ai-card${bm}" data-url="${item.link}">
      <div class="ai-card-head">
        <span class="news-tag ${tagClass(item.tag)}">${item.tag}</span>
        <span class="ai-card-source">${item.source}</span>
        ${upvotes}
      </div>
      <div class="ai-card-title">${item.title}</div>
      <div class="ai-card-desc">${item.description || ""}</div>
      <div class="ai-card-meta">
        <span>${timeAgo(item.published)}</span>
      </div>
    </a>`;
  }

  function renderAi(container, items) {
    if (!items.length) {
      container.innerHTML = `<div class="error-state">No research articles found.</div>`;
      return;
    }
    container.innerHTML = items.map(aiCard).join("");
  }

  function loadAi() {
    return subscribeNews("ai_research", "#aiContainer", (items, c) => {
      allAiItems = items;
      renderAi(c, items);
      updateColCount("aiCount", items.length);
    });
  }

  function applyAiFilter(tag) {
    let items = tag === "all" ? allAiItems : allAiItems.filter((i) => i.tag === tag);
    if (items.length < 2) items = allAiItems;
    renderAi($("#aiContainer"), items);
    updateColCount("aiCount", items.length);
  }

  $$("#aiFilters .pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$("#aiFilters .pill").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      applyAiFilter(btn.dataset.filter);
    });
  });

  // ── Ticker ────────────────────────────────────────────────────────────
  function buildTicker(data) {
    const track = $("#tickerTrack");
    const all = [];
    for (const key of ["india", "us", "commodities"]) {
      for (const s of data[key] || []) all.push(s);
    }
    if (!all.length) {
      track.innerHTML = `<span class="ticker-placeholder">Market data unavailable</span>`;
      return;
    }
    const html = all.map((s) => {
      const dir = s.change >= 0 ? "up" : "down";
      return `<span class="tick">
        <span class="tick-name">${s.label}</span>
        <span class="tick-price">${fmtPrice(s.price, s.currency)}</span>
        <span class="tick-badge ${dir}">${fmtPct(s.change_pct)}</span>
      </span>`;
    }).join('<span class="tick-sep"></span>');
    track.innerHTML = html + '<span class="tick-sep"></span>' + html;
  }

  async function fetchAllStocks() {
    try {
      const r = await fetch("/api/stocks/all");
      if (!r.ok) throw new Error();
      return await r.json();
    } catch {
      return {};
    }
  }

  // ── Trending Papers Banner ────────────────────────────────────────────
  async function fetchTrending() {
    const track = $("#trendingTrack");
    try {
      const r = await fetch("/api/trending");
      if (!r.ok) throw new Error();
      const data = await r.json();
      const papers = data.papers || [];
      if (!papers.length) {
        track.innerHTML = `<span class="trending-placeholder">No trending papers</span>`;
        return;
      }
      const html = papers.slice(0, 20).map((p) => {
        const upvotes = p.upvotes ? `<span class="trending-upvotes">${p.upvotes}</span>` : "";
        return `<a href="${p.link}" target="_blank" rel="noopener" class="trending-card">
          <span class="news-tag ${tagClass(p.tag)}">${p.tag || "ML"}</span>
          <span class="trending-title">${p.title}</span>
          ${upvotes}
        </a>`;
      }).join('<span class="trending-sep"></span>');
      track.innerHTML = html + '<span class="trending-sep"></span>' + html;
    } catch {
      track.innerHTML = `<span class="trending-placeholder">Trending unavailable</span>`;
    }
  }

  // ── Scores Banner ──────────────────────────────────────────────────────
  function scoreCard(m) {
    return `<div class="score-card" data-event-id="${m.event_id}" data-league-code="${m.league_code}" style="cursor:pointer">
      <span class="score-league league-${m.league_short}">${m.league_short}</span>
      <div class="score-teams">
        <span class="score-team">
          ${m.home_logo ? `<img class="score-team-logo" src="${m.home_logo}" alt="" onerror="this.style.display='none'">` : ""}
          <span class="score-team-name">${m.home}</span>
        </span>
        <span class="score-result">${m.home_score} - ${m.away_score}</span>
        <span class="score-team">
          <span class="score-team-name">${m.away}</span>
          ${m.away_logo ? `<img class="score-team-logo" src="${m.away_logo}" alt="" onerror="this.style.display='none'">` : ""}
        </span>
      </div>
      <span class="score-status">${m.status}</span>
    </div>`;
  }

  async function fetchScores() {
    const track = $("#scoresTrack");
    try {
      const r = await fetch("/api/scores");
      if (!r.ok) throw new Error();
      const matches = await r.json();
      if (!matches.length) {
        track.innerHTML = `<span class="scores-placeholder">No recent matches</span>`;
        return;
      }
      const html = matches.map(scoreCard).join('<span class="score-sep"></span>');
      track.innerHTML = html + '<span class="score-sep"></span>' + html;
    } catch {
      track.innerHTML = `<span class="scores-placeholder">Scores unavailable</span>`;
    }
  }

  // ── Article Reader Modal ──────────────────────────────────────────────
  const readerOverlay  = $("#readerOverlay");
  const readerBody     = $("#readerBody");
  const readerSource   = $("#readerSource");
  const readerExtLink  = $("#readerExtLink");
  const readerClose    = $("#readerClose");
  const readerBookmark = $("#readerBookmark");
  let currentReaderItem = null;

  function openReader(url, sourceName, item) {
    currentReaderItem = item || { link: url, title: sourceName, source: sourceName, tag: "General" };
    readerOverlay.classList.add("open");
    document.body.style.overflow = "hidden";
    readerSource.textContent = sourceName || new URL(url).hostname;
    readerExtLink.href = url;
    readerBookmark.classList.toggle("active", isBookmarked(url));
    readerBody.innerHTML = `<div class="reader-loading">
      <div class="skel skel-hero"></div>
      <div class="skel skel-row"></div>
      <div class="skel skel-row"></div>
    </div>`;

    fetch(`/api/article?url=${encodeURIComponent(url)}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          if (data.error === "blocked") {
            closeReader();
            window.open(data.source_url || url, "_blank", "noopener");
            return;
          }
          readerBody.innerHTML = `<div class="reader-error">
            <p>Could not parse this article.</p>
            <p><a href="${url}" target="_blank" rel="noopener">Open in browser instead</a></p>
          </div>`;
          return;
        }

        let html = "";
        if (data.top_image) {
          html += `<img class="reader-top-img" src="${data.top_image}" alt="" onerror="this.style.display='none'">`;
        }
        html += `<h1 class="reader-title">${data.title}</h1>`;

        const metaParts = [];
        if (data.authors && data.authors.length) {
          metaParts.push(`<span class="reader-meta-author">${data.authors.join(", ")}</span>`);
        }
        if (data.publish_date) metaParts.push(`<span>${timeAgo(data.publish_date)}</span>`);
        if (data.readingTime)  metaParts.push(`<span>${data.readingTime} min read</span>`);
        metaParts.push(`<span>${new URL(url).hostname}</span>`);
        html += `<div class="reader-meta">${metaParts.join('<span style="color:var(--border-h)">|</span>')}</div>`;

        const decoded = data.text
          .replace(/&#x27;/g, "'").replace(/&amp;/g, "&")
          .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"');
        const paragraphs = decoded.split(/\n{2,}/).filter((p) => p.trim().length > 0);
        html += `<div class="reader-text">${paragraphs.map((p) => `<p>${p.trim()}</p>`).join("")}</div>`;

        const extraImages = (data.images || []).filter((img) => img !== data.top_image).slice(0, 4);
        if (extraImages.length) {
          html += `<div class="reader-images">${extraImages.map((img) => `<img src="${img}" alt="" loading="lazy" onerror="this.style.display='none'">`).join("")}</div>`;
        }
        readerBody.innerHTML = html;
      })
      .catch(() => {
        readerBody.innerHTML = `<div class="reader-error">
          <p>Failed to load article.</p>
          <p><a href="${url}" target="_blank" rel="noopener">Open in browser instead</a></p>
        </div>`;
      });
  }

  function closeReader() {
    readerOverlay.classList.remove("open");
    document.body.style.overflow = "";
    currentReaderItem = null;
  }

  readerClose.addEventListener("click", closeReader);
  readerOverlay.addEventListener("click", (e) => { if (e.target === readerOverlay) closeReader(); });
  readerBookmark.addEventListener("click", () => {
    if (currentReaderItem) {
      toggleBookmark(currentReaderItem);
      readerBookmark.classList.toggle("active", isBookmarked(currentReaderItem.link));
    }
  });

  document.addEventListener("click", (e) => {
    const link = e.target.closest(".news-hero, .news-row, .ai-card");
    if (!link) return;
    e.preventDefault();
    const url = link.getAttribute("href");
    if (!url) return;
    const sourceEl = link.querySelector(".hero-source, .news-row-source, .ai-card-source");
    const sourceName = sourceEl ? sourceEl.textContent : "";
    const allItems = [...allTopNews, ...allAiItems];
    const item = allItems.find(i => i.link === url) || {
      link: url,
      title: link.querySelector(".hero-title, .news-row-title, .ai-card-title")?.textContent || "",
      source: sourceName,
      tag: "General",
    };
    openReader(url, sourceName, item);
  });

  // ── Match Stats Modal ──────────────────────────────────────────────────
  function openMatchStats(leagueCode, eventId) {
    readerOverlay.classList.add("open");
    document.body.style.overflow = "hidden";
    readerSource.textContent = "Match Stats";
    readerExtLink.href = `https://www.espn.com/soccer/match/_/gameId/${eventId}`;
    readerBody.innerHTML = `<div class="reader-loading">
      <div class="skel skel-hero"></div>
      <div class="skel skel-row"></div>
      <div class="skel skel-row"></div>
    </div>`;

    fetch(`/api/match/${leagueCode}/${eventId}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          readerBody.innerHTML = `<div class="reader-error"><p>Could not load match stats.</p></div>`;
          return;
        }
        const home = data.teams.find((t) => t.home_away === "home") || data.teams[0] || {};
        const away = data.teams.find((t) => t.home_away === "away") || data.teams[1] || {};

        let html = `<div class="match-header">
          <div class="match-team-col">
            ${home.logo ? `<img class="match-team-logo" src="${home.logo}" alt="">` : ""}
            <span class="match-team-name">${home.name}</span>
          </div>
          <div class="match-score-col">
            <span class="match-score-big">${home.score} - ${away.score}</span>
          </div>
          <div class="match-team-col">
            ${away.logo ? `<img class="match-team-logo" src="${away.logo}" alt="">` : ""}
            <span class="match-team-name">${away.name}</span>
          </div>
        </div>`;

        if (data.venue || data.attendance) {
          html += `<div class="match-venue">`;
          if (data.venue) html += `<span>${data.venue}</span>`;
          if (data.attendance) html += `<span>Attendance: ${Number(data.attendance).toLocaleString()}</span>`;
          html += `</div>`;
        }

        if (data.events.length) {
          html += `<div class="match-events">`;
          for (const ev of data.events) {
            let icon = "";
            if (ev.type === "Goal" || ev.type === "Penalty - Scored") icon = "\u26BD";
            else if (ev.type === "Own Goal")    icon = "\u26BD\u200B(OG)";
            else if (ev.type === "Yellow Card") icon = "\uD83D\uDFE8";
            else if (ev.type === "Red Card")    icon = "\uD83D\uDFE5";
            else if (ev.type === "Substitution") icon = "\uD83D\uDD04";
            else if (ev.type === "Penalty - Missed") icon = "\u274C";
            html += `<div class="match-event ${ev.team === home.name ? "ev-home" : "ev-away"}">
              <span class="ev-clock">${ev.clock}</span>
              <span class="ev-icon">${icon}</span>
              <span class="ev-player">${ev.player}</span>
            </div>`;
          }
          html += `</div>`;
        }

        if (data.stats.length >= 2) {
          const hs = data.stats[0].stats;
          const as_ = data.stats[1].stats;
          html += `<div class="match-stats-grid">`;
          for (const key of Object.keys(hs)) {
            const hv = hs[key], av = as_[key];
            if (hv === "-" && av === "-") continue;
            const hn = parseFloat(hv) || 0;
            const an = parseFloat(av) || 0;
            const total = hn + an || 1;
            const hPct = (hn / total) * 100;
            const isPoss = key === "Possession";
            html += `<div class="stat-row">
              <span class="stat-label">${key}</span>
              <span class="stat-val-l">${isPoss ? hv + "%" : hv}</span>
              <div class="stat-bar-wrap">
                <div class="stat-bar-home" style="width:${hPct}%"></div>
                <div class="stat-bar-away" style="width:${100 - hPct}%"></div>
              </div>
              <span class="stat-val-r">${isPoss ? av + "%" : av}</span>
            </div>`;
          }
          html += `</div>`;
        }
        readerBody.innerHTML = html;
      })
      .catch(() => {
        readerBody.innerHTML = `<div class="reader-error"><p>Failed to load match stats.</p></div>`;
      });
  }

  document.addEventListener("click", (e) => {
    const card = e.target.closest(".score-card[data-event-id]");
    if (!card) return;
    const { eventId, leagueCode } = card.dataset;
    if (eventId && leagueCode) openMatchStats(leagueCode, eventId);
  });

  // ── Keyboard Navigation ────────────────────────────────────────────────
  let focusedIdx = -1;
  let kbdHintTimeout = null;

  function getNavigableItems() { return Array.from($$(".news-hero, .news-row, .ai-card")); }
  function clearFocus() { $$(".kb-focus").forEach(el => el.classList.remove("kb-focus")); }

  function setFocus(idx) {
    const items = getNavigableItems();
    if (idx < 0 || idx >= items.length) return;
    clearFocus();
    focusedIdx = idx;
    items[idx].classList.add("kb-focus");
    items[idx].scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function showKbdHint() {
    const hint = $("#kbdHint");
    hint.classList.add("visible");
    clearTimeout(kbdHintTimeout);
    kbdHintTimeout = setTimeout(() => hint.classList.remove("visible"), 4000);
  }

  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea, select")) {
      if (e.key === "Escape") e.target.blur();
      return;
    }
    const readerOpen = readerOverlay.classList.contains("open");

    switch (e.key) {
      case "Escape":
        if (readerOpen) closeReader();
        else if (bookmarksPanel.classList.contains("open")) bookmarksPanel.classList.remove("open");
        break;
      case "j":
        if (readerOpen) return;
        e.preventDefault();
        setFocus(Math.min(focusedIdx + 1, getNavigableItems().length - 1));
        break;
      case "k":
        if (readerOpen) return;
        e.preventDefault();
        setFocus(Math.max(focusedIdx - 1, 0));
        break;
      case "o":
      case "Enter": {
        if (readerOpen) return;
        e.preventDefault();
        const items = getNavigableItems();
        if (focusedIdx >= 0 && focusedIdx < items.length) items[focusedIdx].click();
        break;
      }
      case "s":
        if (readerOpen && currentReaderItem) {
          toggleBookmark(currentReaderItem);
          readerBookmark.classList.toggle("active", isBookmarked(currentReaderItem.link));
        } else if (!readerOpen) {
          const navItems = getNavigableItems();
          if (focusedIdx >= 0 && focusedIdx < navItems.length) {
            const url = navItems[focusedIdx].getAttribute("href") || navItems[focusedIdx].dataset.url;
            const item = [...allTopNews, ...allAiItems].find(i => i.link === url);
            if (item) {
              toggleBookmark(item);
              navItems[focusedIdx].classList.toggle("bookmarked", isBookmarked(url));
            }
          }
        }
        break;
      case "/":
        if (readerOpen) return;
        e.preventDefault();
        searchInput.focus();
        break;
      case "b":
        if (readerOpen) return;
        bookmarksPanel.classList.toggle("open");
        if (bookmarksPanel.classList.contains("open")) renderBookmarks();
        break;
      case "?":
        if (readerOpen) return;
        showKbdHint();
        break;
      case "r":
        if (readerOpen) return;
        loadAll();
        break;
    }
  });

  // ── Boot ──────────────────────────────────────────────────────────────
  async function loadAll() {
    const btn = $("#refreshAll");
    btn.classList.add("spinning");

    // SSE streams for news (non-blocking — they push as data arrives)
    loadTopNews();
    loadFootball();
    loadAi();

    // Parallel: stocks + scores + trending (one-shot fetch, not SSE)
    const [stockData] = await Promise.all([
      fetchAllStocks(),
      fetchScores(),
      fetchTrending(),
    ]);

    buildTicker(stockData || {});
    stampUpdate();
    btn.classList.remove("spinning");
  }

  loadAll();
  $("#refreshAll").addEventListener("click", loadAll);

  // No setInterval — SSE eliminates the need for scheduled polling.
  // Columns resize on window change.
  window.addEventListener("resize", () => {
    adjustColumns(allTopNews.length, 0, allAiItems.length);
  });

})();

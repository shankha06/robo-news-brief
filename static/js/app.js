/* =========================================================================
   Daily Chore Dashboard – Frontend
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

  // ── Header ──────────────────────────────────────────────────────────
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

  // ── Search ──────────────────────────────────────────────────────────
  function doSearch() {
    const q = $("#searchInput").value.trim();
    if (!q) return;
    window.open(`https://www.google.com/search?q=${encodeURIComponent(q)}`, "_blank");
  }

  $("#searchInput").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); doSearch(); } });

  // ── News Rendering ──────────────────────────────────────────────────
  let allTopNews = [];

  function heroCard(item) {
    return `<a href="${item.link}" target="_blank" rel="noopener" class="news-hero">
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
      ? `<img class="news-row-thumb" src="${item.thumbnail}" alt="" loading="lazy" onerror="this.style.display='none'">`
      : "";
    return `<a href="${item.link}" target="_blank" rel="noopener" class="news-row">
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

  async function fetchNews(cat, containerId) {
    const c = $(containerId);
    try {
      const r = await fetch(`/api/news/${cat}`);
      if (!r.ok) throw new Error();
      const items = await r.json();
      if (cat === "top_news") {
        allTopNews = items;
        renderNews(c, items, true);
      } else if (cat === "football") {
        renderNews(c, items, false);
      }
      return items;
    } catch {
      c.innerHTML = `<div class="error-state">Failed to load. Try refreshing.</div>`;
      return [];
    }
  }

  // ── News Filters ────────────────────────────────────────────────────
  function applyNewsFilter(tag) {
    let items = tag === "all" ? allTopNews : allTopNews.filter((i) => i.tag === tag);
    if (items.length < 3) items = allTopNews;
    renderNews($("#topNewsContainer"), items, true);
  }

  $$("#newsFilters .pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$("#newsFilters .pill").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      applyNewsFilter(btn.dataset.filter);
    });
  });

  // ── AI Research Rendering ─────────────────────────────────────────
  let allAiItems = [];

  function aiCard(item) {
    return `<a href="${item.link}" target="_blank" rel="noopener" class="ai-card">
      <div class="ai-card-head">
        <span class="news-tag ${tagClass(item.tag)}">${item.tag}</span>
        <span class="ai-card-source">${item.source}</span>
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

  async function fetchAi() {
    const c = $("#aiContainer");
    try {
      const r = await fetch("/api/news/ai_research");
      if (!r.ok) throw new Error();
      allAiItems = await r.json();
      renderAi(c, allAiItems);
    } catch {
      c.innerHTML = `<div class="error-state">Failed to load. Try refreshing.</div>`;
    }
  }

  function applyAiFilter(tag) {
    let items = tag === "all" ? allAiItems : allAiItems.filter((i) => i.tag === tag);
    if (items.length < 2) items = allAiItems;
    renderAi($("#aiContainer"), items);
  }

  $$("#aiFilters .pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$("#aiFilters .pill").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      applyAiFilter(btn.dataset.filter);
    });
  });

  // ── Ticker ──────────────────────────────────────────────────────────
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

  // ── Scores Banner ──────────────────────────────────────────────────
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

  // ── Article Reader Modal ────────────────────────────────────────────
  const readerOverlay = $("#readerOverlay");
  const readerBody = $("#readerBody");
  const readerSource = $("#readerSource");
  const readerExtLink = $("#readerExtLink");
  const readerClose = $("#readerClose");

  function openReader(url, sourceName) {
    readerOverlay.classList.add("open");
    document.body.style.overflow = "hidden";
    readerSource.textContent = sourceName || new URL(url).hostname;
    readerExtLink.href = url;
    readerBody.innerHTML = `<div class="reader-loading">
      <div class="skel skel-hero"></div>
      <div class="skel skel-row"></div>
      <div class="skel skel-row"></div>
    </div>`;

    fetch(`/api/article?url=${encodeURIComponent(url)}`)
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          // If site blocks server-side fetching, open directly in browser
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
        if (data.publish_date) {
          metaParts.push(`<span>${timeAgo(data.publish_date)}</span>`);
        }
        metaParts.push(`<span>${new URL(url).hostname}</span>`);
        html += `<div class="reader-meta">${metaParts.join('<span style="color:var(--border-h)">|</span>')}</div>`;

        // Decode HTML entities and convert text paragraphs to HTML
        const decoded = data.text.replace(/&#x27;/g, "'").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"');
        const paragraphs = decoded.split(/\n{2,}/).filter((p) => p.trim().length > 0);
        html += `<div class="reader-text">${paragraphs.map((p) => `<p>${p.trim()}</p>`).join("")}</div>`;

        // Extra images (skip top_image)
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
  }

  readerClose.addEventListener("click", closeReader);
  readerOverlay.addEventListener("click", (e) => {
    if (e.target === readerOverlay) closeReader();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && readerOverlay.classList.contains("open")) closeReader();
  });

  // Intercept news/article clicks to open in reader
  document.addEventListener("click", (e) => {
    const link = e.target.closest(".news-hero, .news-row, .ai-card");
    if (!link) return;
    e.preventDefault();
    const url = link.getAttribute("href");
    if (!url) return;
    const sourceEl = link.querySelector(".hero-source, .news-row-source, .ai-card-source");
    const sourceName = sourceEl ? sourceEl.textContent : "";
    openReader(url, sourceName);
  });

  // ── Match Stats Modal ───────────────────────────────────────────────
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

        // Key events
        if (data.events.length) {
          html += `<div class="match-events">`;
          for (const ev of data.events) {
            let icon = "";
            if (ev.type === "Goal" || ev.type === "Penalty - Scored") icon = "\u26BD";
            else if (ev.type === "Own Goal") icon = "\u26BD\u200B(OG)";
            else if (ev.type === "Yellow Card") icon = "\uD83D\uDFE8";
            else if (ev.type === "Red Card") icon = "\uD83D\uDFE5";
            else if (ev.type === "Substitution") icon = "\uD83D\uDD04";
            else if (ev.type === "Penalty - Missed") icon = "\u274C";
            const isHome = ev.team === home.name;
            html += `<div class="match-event ${isHome ? "ev-home" : "ev-away"}">
              <span class="ev-clock">${ev.clock}</span>
              <span class="ev-icon">${icon}</span>
              <span class="ev-player">${ev.player}</span>
            </div>`;
          }
          html += `</div>`;
        }

        // Stats comparison bars
        if (data.stats.length >= 2) {
          const hs = data.stats[0].stats;
          const as_ = data.stats[1].stats;
          html += `<div class="match-stats-grid">`;
          for (const key of Object.keys(hs)) {
            const hv = hs[key];
            const av = as_[key];
            if (hv === "-" && av === "-") continue;
            const hn = parseFloat(hv) || 0;
            const an = parseFloat(av) || 0;
            const total = hn + an || 1;
            const hPct = (hn / total) * 100;
            // Possession special: values are already percentages
            const isPoss = key === "Possession";
            const hDisp = isPoss ? `${hv}%` : hv;
            const aDisp = isPoss ? `${av}%` : av;
            html += `<div class="stat-row">
              <span class="stat-label">${key}</span>
              <span class="stat-val-l">${hDisp}</span>
              <div class="stat-bar-wrap">
                <div class="stat-bar-home" style="width:${hPct}%"></div>
                <div class="stat-bar-away" style="width:${100 - hPct}%"></div>
              </div>
              <span class="stat-val-r">${aDisp}</span>
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

  // Intercept score card clicks
  document.addEventListener("click", (e) => {
    const card = e.target.closest(".score-card[data-event-id]");
    if (!card) return;
    const eventId = card.dataset.eventId;
    const leagueCode = card.dataset.leagueCode;
    if (eventId && leagueCode) {
      openMatchStats(leagueCode, eventId);
    }
  });

  // ── Boot ────────────────────────────────────────────────────────────
  async function loadAll() {
    const btn = $("#refreshAll");
    btn.classList.add("spinning");

    const [stockData] = await Promise.all([
      fetchAllStocks(),
      fetchNews("top_news", "#topNewsContainer"),
      fetchNews("football", "#footballContainer"),
      fetchAi(),
      fetchScores(),
    ]);

    buildTicker(stockData || {});
    stampUpdate();
    btn.classList.remove("spinning");
  }

  loadAll();
  $("#refreshAll").addEventListener("click", loadAll);
  setInterval(loadAll, 5 * 60 * 1000);

})();

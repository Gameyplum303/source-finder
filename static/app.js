"use strict";

// All article data comes from third-party APIs, so it is treated as untrusted:
// it is only ever written with textContent (never innerHTML), and links are
// accepted only if they parse as http(s) URLs.

(() => {
  const form = document.getElementById("search-form");
  const input = document.getElementById("q");
  const statusEl = document.getElementById("status");
  const list = document.getElementById("results");
  const moreBtn = document.getElementById("more");
  const submitBtn = form.querySelector("button");
  const template = document.getElementById("card-template");
  const sortSelect = document.getElementById("sort");
  const sortWrap = document.getElementById("sort-wrap");

  let currentQuery = "";
  let nextToken = null;
  let articles = [];
  let shown = new Set();
  let rejected = 0;
  let controller = null;
  let aiEnabled = false;

  function setStatus(message, warn = false) {
    statusEl.textContent = message;
    statusEl.classList.toggle("warn", warn);
  }

  function safeHref(value) {
    try {
      const url = new URL(value);
      return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
    } catch {
      return null;
    }
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function levelClass(level) {
    return { Low: "low", Moderate: "moderate", High: "high" }[level] || "moderate";
  }

  function renderChecks(container, article) {
    const quality = article.quality && typeof article.quality === "object" ? article.quality : {};
    const add = (text, title) => {
      const item = el("li", "check", text);
      if (title) item.title = title;
      container.append(item);
    };
    if (quality.peer_reviewed) {
      add(quality.venue_type === "conference" ? "Peer-reviewed conference" : "Peer-reviewed journal");
    }
    const vetted = Array.isArray(quality.vetted_by) ? quality.vetted_by : [];
    if (vetted.length) {
      add(`Expert-vetted: ${vetted.map((v) => String(v.label)).join(", ")}`,
          vetted.map((v) => String(v.detail)).join("\n"));
    }
    if (quality.not_retracted) add("Not retracted");
    if (typeof quality.field === "string" && quality.field) {
      container.append(el("li", "check neutral", quality.field));
    }
    if (article.bias && typeof article.bias.design === "string") {
      container.append(el("li", "check neutral", article.bias.design));
    }
    if (typeof quality.top_cited === "string" && quality.top_cited) {
      container.append(el("li", "check star", quality.top_cited));
    }
  }

  function renderBias(node, bias) {
    const box = node.querySelector(".bias");
    const score = Number(bias && bias.score);
    if (!Number.isFinite(score)) {
      box.remove();
      return;
    }
    const pct = Math.max(0, Math.min(100, Math.round(score)));
    const level = typeof bias.level === "string" ? bias.level : "";
    box.classList.add(levelClass(level));
    node.querySelector(".bias-value").textContent = `${pct}% · ${level} risk`;
    // CSSOM property writes are allowed by our CSP (inline style attributes are not).
    node.querySelector(".bias-fill").style.width = `${pct}%`;
    const track = node.querySelector(".bias-track");
    track.setAttribute("role", "img");
    track.setAttribute("aria-label", `Estimated risk of bias ${pct} percent, ${level}`);

    const factors = node.querySelector(".factors");
    for (const f of Array.isArray(bias.factors) ? bias.factors : []) {
      const item = el("li", "factor");
      const head = el("div", "factor-head");
      head.append(el("span", "factor-name", `${f.name} (weight ${Number(f.weight)}%)`));
      head.append(el("span", "factor-risk", `${Number(f.risk)}% risk`));
      item.append(head, el("p", "factor-detail", String(f.detail)));
      factors.append(item);
    }
  }

  const RATING_CLASS = { Low: "low", "Some concerns": "moderate", High: "high", Unclear: "unclear" };

  function renderReview(container, review) {
    const score = Math.max(0, Math.min(100, Math.round(Number(review.score) || 0)));
    const level = typeof review.level === "string" ? review.level : "";
    const box = el("div", `ai-box ${levelClass(level)}`);

    const head = el("div", "bias-head");
    head.append(el("span", "bias-label", "AI-estimated risk of bias"),
                el("span", "bias-value", `${score}% · ${level} risk`));
    const track = el("div", "bias-track");
    const fill = el("div", "bias-fill");
    fill.style.width = `${score}%`;
    track.append(fill);
    box.append(head, track);

    if (review.study_design) box.append(el("p", "ai-design", `Design: ${review.study_design}`));
    if (review.summary) box.append(el("p", "ai-summary", review.summary));

    const domains = Array.isArray(review.domains) ? review.domains : [];
    if (domains.length) {
      const list = el("ul", "ai-domains");
      for (const d of domains) {
        const item = el("li", "ai-domain");
        const top = el("div", "ai-domain-head");
        top.append(el("span", "ai-domain-name", String(d.domain)),
                   el("span", `rating ${RATING_CLASS[d.rating] || "unclear"}`, String(d.rating)));
        item.append(top, el("p", "factor-detail", String(d.explanation)));
        list.append(item);
      }
      box.append(list);
    }

    for (const [key, label] of [["strengths", "Strengths"], ["concerns", "Concerns"]]) {
      const items = Array.isArray(review[key]) ? review[key] : [];
      if (!items.length) continue;
      box.append(el("h3", "ai-subhead", label));
      const list = el("ul", "ai-points");
      for (const text of items) list.append(el("li", null, String(text)));
      box.append(list);
    }

    box.append(el("p", "ai-footer",
      `Confidence: ${review.confidence || "Low"} (abstract only). AI-generated by Claude and can be wrong.`));
    container.replaceChildren(box);
    container.hidden = false;
  }

  async function requestReview(node, article) {
    const btn = node.querySelector(".ai-btn");
    const errorEl = node.querySelector(".ai-error");
    btn.disabled = true;
    btn.textContent = "Reviewing…";
    errorEl.hidden = true;
    try {
      const resp = await fetch("/api/ai-review", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ doi: article.doi }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || !data.review || typeof data.review !== "object") {
        throw new Error(typeof data.error === "string" ? data.error : "The AI review failed. Please try again.");
      }
      renderReview(node.querySelector(".ai-result"), data.review);
      node.querySelector(".ai-cta").hidden = true;
    } catch (err) {
      errorEl.textContent = err instanceof TypeError ? "Could not reach the server." : err.message;
      errorEl.hidden = false;
      btn.disabled = false;
      btn.textContent = "Try AI review again";
    }
  }

  function renderArticle(article) {
    const href = safeHref(article.url);
    if (!href || typeof article.title !== "string") return null;

    const node = template.content.firstElementChild.cloneNode(true);
    const link = node.querySelector(".title a");
    link.href = href;
    link.textContent = article.title;

    const meta = [];
    if (Array.isArray(article.authors) && article.authors.length) {
      const names = article.authors.slice(0, 3).join(", ");
      meta.push(article.authors.length > 3 ? `${names} et al.` : names);
    }
    if (article.journal) meta.push(article.journal);
    if (Number.isInteger(article.year)) meta.push(String(article.year));
    node.querySelector(".meta").textContent = meta.join(" · ");

    renderChecks(node.querySelector(".checks"), article);
    node.querySelector(".synopsis").textContent = article.synopsis || "";
    renderBias(node, article.bias);
    const ai = node.querySelector(".ai");
    if (ai && aiEnabled && typeof article.doi === "string" && article.doi) {
      ai.hidden = false;
      node.querySelector(".ai-btn").addEventListener("click", () => requestReview(node, article));
    }

    const badges = node.querySelector(".badges");
    if (article.source) badges.append(el("span", "badge", `via ${article.source}`));
    if (Number.isInteger(article.citations)) {
      badges.append(el("span", "badge", `${article.citations.toLocaleString()} citations`));
    }
    if (article.open_access) badges.append(el("span", "badge oa", "Free to read"));
    if (article.doi) badges.append(el("span", "badge", `DOI ${article.doi}`));
    return node;
  }

  const sorters = {
    relevance: (a, b) => a.order - b.order,
    bias: (a, b) => (a.data.bias?.score ?? 101) - (b.data.bias?.score ?? 101) || a.order - b.order,
    citations: (a, b) => (b.data.citations ?? -1) - (a.data.citations ?? -1) || a.order - b.order,
    year: (a, b) => (b.data.year ?? 0) - (a.data.year ?? 0) || a.order - b.order,
  };

  function renderList() {
    const sorter = sorters[sortSelect.value] || sorters.relevance;
    list.replaceChildren(...[...articles].sort(sorter).map((a) => a.node));
  }

  function updateStatus(unavailable) {
    const total = articles.length;
    let message = total
      ? `Showing ${total} vetted article${total === 1 ? "" : "s"} for “${currentQuery}”.`
      : `No articles passed the quality checks for “${currentQuery}”. Try broader or different wording.`;
    if (rejected) {
      message += ` ${rejected} other result${rejected === 1 ? "" : "s"} hidden for failing quality checks.`;
    }
    if (unavailable.length) {
      message += ` (${unavailable.join(", ")} did not respond, so results may be incomplete.)`;
    }
    setStatus(message, unavailable.length > 0);
  }

  async function runSearch(query, token) {
    if (controller) controller.abort();
    controller = new AbortController();

    const params = new URLSearchParams({ q: query });
    if (token) params.set("cursor", token);

    submitBtn.disabled = true;
    moreBtn.disabled = true;
    setStatus(token ? "Loading and vetting more articles…" : "Searching and vetting peer-reviewed literature…");

    let data;
    try {
      const resp = await fetch(`/api/search?${params}`, {
        signal: controller.signal,
        headers: { Accept: "application/json" },
      });
      data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        setStatus(typeof data.error === "string" ? data.error : "Search failed. Please try again.", true);
        return;
      }
    } catch (err) {
      if (err.name !== "AbortError") setStatus("Could not reach the server. Please try again.", true);
      return;
    } finally {
      submitBtn.disabled = false;
      moreBtn.disabled = false;
    }

    aiEnabled = data.ai_review === true;
    for (const article of Array.isArray(data.results) ? data.results : []) {
      const id = typeof article.id === "string" ? article.id : article.url;
      if (shown.has(id)) continue;
      const node = renderArticle(article);
      if (node) {
        shown.add(id);
        articles.push({ data: article, node, order: articles.length });
      }
    }
    if (Number.isInteger(data.rejected)) rejected += data.rejected;

    renderList();
    sortWrap.hidden = articles.length < 2;
    nextToken = typeof data.next === "string" ? data.next : null;
    moreBtn.hidden = !nextToken;
    updateStatus(Array.isArray(data.unavailable) ? data.unavailable : []);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = input.value.trim().replace(/\s+/g, " ");
    if (query.length < 3) {
      setStatus("Please enter at least 3 characters.", true);
      return;
    }
    currentQuery = query;
    nextToken = null;
    articles = [];
    shown = new Set();
    rejected = 0;
    list.replaceChildren();
    moreBtn.hidden = true;
    sortWrap.hidden = true;
    history.replaceState(null, "", `?${new URLSearchParams({ q: query })}`);
    runSearch(query, null);
  });

  sortSelect.addEventListener("change", renderList);

  moreBtn.addEventListener("click", () => {
    if (nextToken && currentQuery) runSearch(currentQuery, nextToken);
  });

  // Allow sharing a search via ?q=... in the address bar.
  const initial = new URLSearchParams(location.search).get("q");
  if (initial) {
    input.value = initial.slice(0, 200);
    form.requestSubmit();
  }
})();

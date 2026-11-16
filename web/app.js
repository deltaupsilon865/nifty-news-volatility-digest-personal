/* Nifty News Volatility Digest - static front end.
   Reads pre-built JSON from ./data (copied in at deploy time). Never calls an LLM.
   Portfolio CSVs are parsed in the browser and kept only in memory. */
"use strict";

const EVENT_LABELS = {
  earnings: "Earnings", corporate_action: "Corporate action", order_win: "Order win",
  management_change: "Management change", regulatory: "Regulatory (SEBI/RBI)",
  macro_data: "Macro data", monetary_policy: "Monetary policy", global_cues: "Global cues",
  commodity_currency: "Commodity / currency", block_bulk_deal: "Block / bulk deal",
  rating_change: "Rating change", legal_penalty: "Legal / penalty", other: "Other",
};
const DIRECTIONS = {
  bullish: { icon: "▲", label: "Bullish" }, bearish: { icon: "▼", label: "Bearish" },
  mixed: { icon: "◆", label: "Mixed" }, uncertain: { icon: "●", label: "Uncertain" },
};
const CAPS = ["Large", "Mid", "Small", "Penny", "Unknown"];
const TOP_N = 10;

const state = {
  dates: [], digest: null, holdings: {},
  filters: defaultFilters(),
  accuracyLoaded: false,
};

function defaultFilters() {
  return { caps: new Set(CAPS), showIndex: true, minSev: 1,
           dirs: new Set(Object.keys(DIRECTIONS)), sector: "", event: "", q: "" };
}

/* ---------------- helpers ---------------- */
const $ = (id) => document.getElementById(id);
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function safeUrl(u) {
  try { const url = new URL(u); return /^https?:$/.test(url.protocol) ? url.href : "#"; } catch { return "#"; }
}
const inr = (x, d = 2) => "₹" + Number(x).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
function inrShort(x) {
  const sign = x < 0 ? "−" : "+"; const a = Math.abs(x);
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(2)} cr`;
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(2)} L`;
  return `${sign}₹${Math.round(a).toLocaleString("en-IN")}`;
}
const IST = { timeZone: "Asia/Kolkata" };
function fmtIST(iso, opts) { return new Date(iso).toLocaleString("en-IN", { ...IST, ...opts }); }
function fmtDay(d) {
  return new Date(d + "T00:00:00+05:30").toLocaleDateString("en-IN", { ...IST, weekday: "short", day: "2-digit", month: "short", year: "numeric" });
}
async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}
function bucketOf(s) { return s.is_index ? "Index" : s.is_penny ? "Penny" : (s.cap_bucket || "Unknown"); }
function sevClass(n) { return n >= 7 ? "sev-hi" : n >= 4 ? "sev-mid" : "sev-lo"; }

/* ---------------- tooltip ---------------- */
const tip = $("tooltip");
function showTip(html, x, y) {
  tip.innerHTML = html; tip.hidden = false;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(window.innerWidth - w - 8, x + 12) + "px";
  tip.style.top = Math.max(8, y - h - 10) + "px";
}
function hideTip() { tip.hidden = true; }

/* ---------------- chart (SVG candles + expected range) ---------------- */
function rangeChart(stock, tradingDate) {
  const er = stock.expected_range;
  if (!er || !er.history || !er.history.length) return "";
  const h = er.history;
  const W = 560, H = 220, padL = 8, padR = 70, padT = 10, padB = 22;
  const lows = h.map((p) => p.low).concat(er.expected_low);
  const highs = h.map((p) => p.high).concat(er.expected_high);
  let lo = Math.min(...lows), hi = Math.max(...highs);
  const pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
  const n = h.length + 1;                                  // + expected column
  const step = (W - padL - padR) / n;
  const bw = Math.max(3, Math.min(14, step * 0.6));
  const y = (v) => padT + (hi - v) / (hi - lo) * (H - padT - padB);
  const x = (i) => padL + step * i + step / 2;
  const ticks = 4, parts = [];
  for (let t = 0; t <= ticks; t++) {
    const v = lo + (hi - lo) * t / ticks, yy = y(v).toFixed(1);
    parts.push(`<line x1="${padL}" x2="${W - padR}" y1="${yy}" y2="${yy}" stroke="var(--grid)" stroke-width="1"/>`);
    parts.push(`<text x="${W - padR + 6}" y="${(+yy + 4).toFixed(1)}" font-size="13" fill="var(--ink-3)">${v.toLocaleString("en-IN", { maximumFractionDigits: v > 1000 ? 0 : 1 })}</text>`);
  }
  h.forEach((p, i) => {
    const up = p.close >= p.open, col = up ? "var(--up)" : "var(--down)";
    const top = y(Math.max(p.open, p.close)), bot = y(Math.min(p.open, p.close));
    parts.push(`<line x1="${x(i).toFixed(1)}" x2="${x(i).toFixed(1)}" y1="${y(p.high).toFixed(1)}" y2="${y(p.low).toFixed(1)}" stroke="${col}" stroke-width="1.2"/>`);
    parts.push(`<rect x="${(x(i) - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1, bot - top).toFixed(1)}" rx="1.5" fill="${col}"/>`);
    parts.push(`<rect class="hit" data-i="${i}" x="${(x(i) - step / 2).toFixed(1)}" y="${padT}" width="${step.toFixed(1)}" height="${H - padT - padB}" fill="transparent"/>`);
  });
  const ei = h.length, ex = x(ei);
  parts.push(`<rect x="${(ex - bw).toFixed(1)}" y="${y(er.expected_high).toFixed(1)}" width="${(bw * 2).toFixed(1)}" height="${(y(er.expected_low) - y(er.expected_high)).toFixed(1)}" rx="3" fill="var(--band)" stroke="var(--band-line)" stroke-width="1.2" stroke-dasharray="3 2"/>`);
  parts.push(`<rect class="hit" data-i="exp" x="${(ex - step / 2).toFixed(1)}" y="${padT}" width="${step.toFixed(1)}" height="${H - padT - padB}" fill="transparent"/>`);
  const pc = y(er.prev_close).toFixed(1);
  parts.push(`<line x1="${padL}" x2="${W - padR}" y1="${pc}" y2="${pc}" stroke="var(--ink-3)" stroke-width="1" stroke-dasharray="2 3"/>`);
  parts.push(`<text x="${padL}" y="${H - 6}" font-size="13" fill="var(--ink-3)">${esc(h[0].date.slice(5))}</text>`);
  parts.push(`<text x="${x(h.length - 1).toFixed(1)}" y="${H - 6}" font-size="13" fill="var(--ink-3)" text-anchor="middle">${esc(h[h.length - 1].date.slice(5))}</text>`);
  parts.push(`<text x="${ex.toFixed(1)}" y="${H - 6}" font-size="13" fill="var(--band-line)" text-anchor="middle" font-weight="600">Exp.</text>`);
  const data = esc(JSON.stringify({ h, er, d: tradingDate }));
  return `<div class="chart">
    <p class="chart-title">${esc(stock.symbol)} · last ${h.length} sessions + expected range</p>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(stock.symbol)} daily candles with expected range ${inr(er.expected_low)} to ${inr(er.expected_high)}" data-chart="${data}">${parts.join("")}</svg>
    <div class="legend"><span><i style="background:var(--up)"></i>Up day</span><span><i style="background:var(--down)"></i>Down day</span><span><i style="background:var(--band);border:1px dashed var(--band-line)"></i>Expected range</span><span>┄ Prev close</span></div>
  </div>`;
}
document.addEventListener("mousemove", (e) => {
  const hit = e.target.closest && e.target.closest("rect.hit");
  if (!hit) { hideTip(); return; }
  const svg = hit.closest("svg"); const { h, er, d } = JSON.parse(svg.dataset.chart);
  const i = hit.dataset.i;
  if (i === "exp") {
    showTip(`<b>${esc(d)} expected</b><br>High ${inr(er.expected_high)}<br>Low ${inr(er.expected_low)}<br>Prev close ${inr(er.prev_close)}<br>ATR ${er.baseline_atr_pct}% × ${er.multiplier}`, e.clientX, e.clientY);
  } else {
    const p = h[+i];
    showTip(`<b>${esc(p.date)}</b><br>O ${inr(p.open)} · H ${inr(p.high)}<br>L ${inr(p.low)} · C ${inr(p.close)}`, e.clientX, e.clientY);
  }
});
document.addEventListener("scroll", hideTip, { passive: true });

/* ---------------- digest rendering ---------------- */
function stockLine(s) {
  const er = s.expected_range;
  let html = `<b>${esc(s.symbol)}</b>`;
  if (!s.is_index) {
    const b = bucketOf(s);
    html += `<span class="tag ${b === "Penny" ? "penny" : ""}">${esc(b === "Penny" ? "Penny" : b + " cap")}</span>`;
  }
  if (s.relation === "indirect") html += `<span class="tag">indirect</span>`;
  if (!er) return html + ` · <span class="muted">range n/a</span>`;
  html += ` · prev ${inr(er.prev_close)} → expected ${inr(er.expected_low)} – ${inr(er.expected_high)}`;
  const q = state.holdings[s.symbol];
  if (q) {
    html += ` · <span class="impact">📌 your ${q.toLocaleString("en-IN")} shares: ${inrShort((er.expected_low - er.prev_close) * q)} / ${inrShort((er.expected_high - er.prev_close) * q)}</span>`;
  }
  return html;
}

function card(it, tradingDate) {
  const d = DIRECTIONS[it.direction] || DIRECTIONS.uncertain;
  const held = it.stocks.some((s) => state.holdings[s.symbol]);
  const when = fmtIST(it.published_at, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
  const cov = it.coverage_count > 1 ? ` · covered by ${it.coverage_count} outlets` : "";
  const first = it.stocks.slice(0, 3).map((s) => `<li class="stock">${stockLine(s)}</li>`).join("");
  const more = it.stocks.slice(3).map((s) => `<li class="stock">${stockLine(s)}</li>`).join("");
  const charts = it.stocks.filter((s) => s.expected_range).slice(0, 3).map((s) => rangeChart(s, tradingDate)).join("");
  const links = (it.covered_by || []).slice(0, 8).map((c) => `<a href="${safeUrl(c.url)}" target="_blank" rel="noopener">${esc(c.source)}</a>`).join(" · ");
  return `<article class="card ${held ? "pinned" : ""}">
    <div class="sev"><span class="num ${sevClass(it.severity)}" title="Severity ${it.severity} of 10">${it.severity}</span><span class="cap">severity</span></div>
    <div>
      <h3>${held ? "📌 " : ""}<span class="rank">#${it.rank}</span><a href="${safeUrl(it.url)}" target="_blank" rel="noopener">${esc(it.title)}</a></h3>
      <div class="meta"><span class="dir dir-${esc(it.direction)}">${d.icon} ${d.label}</span> · ${esc(EVENT_LABELS[it.event_type] || it.event_type)} · ${esc(it.scope.replace("_", " "))} · ${esc(it.source)} · ${esc(when)} IST${cov}</div>
      <p class="why">${esc(it.why_it_matters)}</p>
      ${first ? `<ul class="stocks">${first}</ul>` : ""}
      <details>
        <summary>Details, charts and sources</summary>
        <div class="detail-body">
          ${it.snippet ? `<p class="snippet">${esc(it.snippet)}</p>` : ""}
          <div>Surprise: <b>${esc(it.surprise_factor)}</b> · Confidence: <b>${esc(it.confidence)}</b> · Sectors: ${esc(it.affected_sectors.join(", ") || "—")}</div>
          ${more ? `<ul class="stocks" style="margin-top:6px">${more}</ul>` : ""}
          ${it.unmapped_companies && it.unmapped_companies.length ? `<p class="muted small">Not matched to an NSE symbol: ${esc(it.unmapped_companies.join(", "))}</p>` : ""}
          ${charts ? `<div class="charts">${charts}</div>` : ""}
          ${(it.covered_by || []).length > 1 ? `<p class="small">Also covered by: ${links}</p>` : ""}
        </div>
      </details>
    </div>
  </article>`;
}

function passes(it) {
  const f = state.filters;
  if (it.severity < f.minSev || !f.dirs.has(it.direction)) return false;
  if (f.sector && !it.affected_sectors.includes(f.sector)) return false;
  if (f.event && it.event_type !== f.event) return false;
  if (f.q) {
    const hay = [it.title, it.snippet, ...it.stocks.map((s) => s.symbol + " " + s.name)].join(" ").toLowerCase();
    if (!hay.includes(f.q.toLowerCase())) return false;
  }
  const eq = it.stocks.filter((s) => !s.is_index);
  if (!eq.length) return it.stocks.length || it.scope !== "single_stock" ? f.showIndex : f.caps.has("Unknown");
  return eq.some((s) => f.caps.has(bucketOf(s))) || (f.showIndex && it.scope === "index");
}

function renderDigest() {
  const dg = state.digest; if (!dg) return;
  const vix = dg.india_vix != null
    ? `<div class="value">${dg.india_vix.toFixed(2)}</div><div class="delta">${dg.india_vix_change_pct != null ? (dg.india_vix_change_pct >= 0 ? "▲ " : "▼ ") + Math.abs(dg.india_vix_change_pct).toFixed(2) + "% vs prior close" : ""}</div>`
    : `<div class="value">—</div>`;
  $("metrics").innerHTML = `
    <div class="metric"><div class="label">Trading session</div><div class="value">${esc(new Date(dg.trading_date + "T00:00:00+05:30").toLocaleDateString("en-IN", { ...IST, weekday: "short", day: "2-digit", month: "short" }))}</div></div>
    <div class="metric"><div class="label">Updated (IST)</div><div class="value">${esc(fmtIST(dg.generated_at, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }))}</div></div>
    <div class="metric"><div class="label">Items</div><div class="value">${dg.items.length}</div></div>
    <div class="metric"><div class="label">India VIX</div>${vix}</div>`;
  const mood = $("mood");
  mood.hidden = !(dg.market_mood && dg.market_mood.length);
  mood.innerHTML = (dg.market_mood || []).map((l) => `<p>${esc(l)}</p>`).join("");
  const ev = $("events");
  ev.hidden = !(dg.events && dg.events.length);
  ev.innerHTML = "<b>Today's events:</b> " + (dg.events || []).map((e) => `<span class="event-tag ${e.importance === "high" ? "high" : ""}">${esc(e.name)}</span>`).join("");

  let shown = dg.items.filter(passes);
  if (Object.keys(state.holdings).length) {
    shown = shown.slice().sort((a, b) => {
      const ha = a.stocks.some((s) => state.holdings[s.symbol]) ? 0 : 1;
      const hb = b.stocks.some((s) => state.holdings[s.symbol]) ? 0 : 1;
      return ha - hb || a.rank - b.rank;
    });
  }
  const since = fmtIST(dg.window_start, { weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
  $("showing").textContent = `Showing ${shown.length} of ${dg.items.length} items · news since ${since} IST`;
  const holdingsNote = Object.keys(state.holdings).length ? " · your holdings first" : "";
  const catchup = dg.mode === "catchup";
  let html = "";
  if (catchup) {
    const n = dg.missed_sessions || 0;
    html += `<div class="catchup-note"><b>Catch-up digest.</b> No digest was made for ${n} trading session${n === 1 ? "" : "s"}, so this covers all news since ${esc(since)} IST, ranked by how likely it is to move prices at the next open. Older news the market has already traded through is scored lower.</div>`;
  }
  if (!shown.length) html += `<div class="empty">No items match these filters.</div>`;
  else if (catchup) {
    html += `<h2 class="section-title">All findings, ranked by severity${holdingsNote}</h2>` + shown.map((it) => card(it, dg.trading_date)).join("");
  } else {
    const top = shown.slice(0, TOP_N), rest = shown.slice(TOP_N);
    if (top.length) html += `<h2 class="section-title">Top ${top.length} must-read${holdingsNote}</h2>` + top.map((it) => card(it, dg.trading_date)).join("");
    if (rest.length) html += `<h2 class="section-title">More news</h2>` + rest.map((it) => card(it, dg.trading_date)).join("");
  }
  $("items").innerHTML = html;

  const ss = dg.source_stats || {};
  const ps = dg.pipeline_stats || {};
  $("pipelineDetails").innerHTML = `
    <div class="table-wrap"><table><thead><tr><th>Source</th><th class="num">Items</th><th>Status</th><th class="num">Seconds</th></tr></thead><tbody>
    ${Object.entries(ss).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${esc(v.count)}</td><td>${esc(v.status)}</td><td class="num">${esc(v.seconds)}</td></tr>`).join("")}
    </tbody></table></div>
    <div class="table-wrap"><table><tbody>${Object.entries(ps).map(([k, v]) => `<tr><td>${esc(k.replace(/_/g, " "))}</td><td class="num">${esc(v)}</td></tr>`).join("")}</tbody></table></div>`;
}

function populateFilterOptions() {
  const dg = state.digest;
  const sectors = [...new Set(dg.items.flatMap((i) => i.affected_sectors))].sort();
  const events = [...new Set(dg.items.map((i) => i.event_type))].sort();
  $("sectorSelect").innerHTML = `<option value="">All sectors</option>` + sectors.map((s) => `<option${s === state.filters.sector ? " selected" : ""}>${esc(s)}</option>`).join("");
  $("eventSelect").innerHTML = `<option value="">All event types</option>` + events.map((e) => `<option value="${esc(e)}"${e === state.filters.event ? " selected" : ""}>${esc(EVENT_LABELS[e] || e)}</option>`).join("");
}

function renderChips() {
  $("capChips").innerHTML = CAPS.map((c) => `<button class="chip" data-cap="${c}" aria-pressed="${state.filters.caps.has(c)}">${c}</button>`).join("");
  $("dirChips").innerHTML = Object.entries(DIRECTIONS).map(([k, v]) => `<button class="chip" data-dir="${k}" aria-pressed="${state.filters.dirs.has(k)}">${v.icon} ${v.label}</button>`).join("");
}

/* ---------------- portfolio ---------------- */
function parseCSV(text) {
  const rows = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const cells = []; let cur = "", q = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') { if (q && line[i + 1] === '"') { cur += '"'; i++; } else q = !q; }
      else if (ch === "," && !q) { cells.push(cur); cur = ""; }
      else cur += ch;
    }
    cells.push(cur); rows.push(cells.map((c) => c.trim()));
  }
  return rows;
}
function loadPortfolio(text) {
  const rows = parseCSV(text);
  if (rows.length < 2) throw new Error("the file is empty");
  const head = rows[0].map((h) => h.toLowerCase().replace(/[^a-z]/g, ""));
  const si = head.findIndex((h) => ["symbol", "ticker", "tradingsymbol", "instrument", "stock", "scrip"].includes(h));
  const qi = head.findIndex((h) => ["qty", "quantity", "shares", "units", "quantityavailable"].includes(h));
  if (si < 0 || qi < 0) throw new Error("needs a 'symbol' column and a 'quantity' column");
  const out = {};
  for (const r of rows.slice(1)) {
    const sym = (r[si] || "").toUpperCase().replace(/\.NS$|-EQ$/g, "").trim();
    const q = parseFloat((r[qi] || "").replace(/,/g, ""));
    if (sym && Number.isFinite(q)) out[sym] = (out[sym] || 0) + q;
  }
  return out;
}

/* ---------------- accuracy ---------------- */
async function renderAccuracy() {
  const body = $("accuracyBody");
  if (state.accuracyLoaded) return;
  let text;
  try {
    const r = await fetch("data/evaluation.csv", { cache: "no-cache" });
    if (!r.ok) throw new Error();
    text = await r.text();
  } catch {
    body.innerHTML = `<div class="empty">No evaluations yet. They appear after the first trading session following a digest.</div>`;
    return;
  }
  const rows = parseCSV(text); const head = rows.shift() || [];
  const data = rows.map((r) => Object.fromEntries(head.map((h, i) => [h, r[i]])));
  if (!data.length) { body.innerHTML = `<div class="empty">No evaluations yet.</div>`; return; }
  const within = data.filter((d) => d.within_range === "True").length / data.length;
  const dirRows = data.filter((d) => d.direction_hit === "True" || d.direction_hit === "False");
  const dirHit = dirRows.length ? dirRows.filter((d) => d.direction_hit === "True").length / dirRows.length : null;
  const sessions = new Set(data.map((d) => d.trading_date)).size;
  const bands = [["1-3", 1, 3], ["4-6", 4, 6], ["7-8", 7, 8], ["9-10", 9, 10]].map(([label, a, b]) => {
    const g = data.filter((d) => +d.severity >= a && +d.severity <= b);
    const ratios = g.map((d) => parseFloat(d.range_ratio)).filter(Number.isFinite);
    return { label, n: g.length, within: g.length ? g.filter((d) => d.within_range === "True").length / g.length : null,
             ratio: ratios.length ? ratios.reduce((s, v) => s + v, 0) / ratios.length : null };
  });
  const W = 520, H = 200, pb = 26, pt = 18, bw = 64, gap = (W - bands.length * bw) / (bands.length + 1);
  const bars = bands.map((b, i) => {
    const x = gap + i * (bw + gap); const v = b.within ?? 0; const h = (H - pb - pt) * v; const y = H - pb - h;
    return `<rect x="${x}" y="${y}" width="${bw}" height="${Math.max(0, h)}" rx="4" fill="var(--accent)"><title>Severity ${b.label}: ${b.within == null ? "no data" : Math.round(v * 100) + "% within range"} (${b.n} stock-days)</title></rect>
      <text x="${x + bw / 2}" y="${y - 5}" text-anchor="middle" font-size="11" fill="var(--ink-2)">${b.within == null ? "—" : Math.round(v * 100) + "%"}</text>
      <text x="${x + bw / 2}" y="${H - 8}" text-anchor="middle" font-size="11" fill="var(--ink-3)">Severity ${b.label}</text>`;
  }).join("");
  const recent = data.slice().sort((a, b) => b.trading_date.localeCompare(a.trading_date) || a.rank - b.rank).slice(0, 200);
  body.innerHTML = `
    <div class="metrics">
      <div class="metric"><div class="label">Sessions evaluated</div><div class="value">${sessions}</div></div>
      <div class="metric"><div class="label">Stock-days</div><div class="value">${data.length}</div></div>
      <div class="metric"><div class="label">Within expected range</div><div class="value">${Math.round(within * 100)}%</div></div>
      <div class="metric"><div class="label">Direction correct</div><div class="value">${dirHit == null ? "—" : Math.round(dirHit * 100) + "%"}</div></div>
    </div>
    <h2 class="section-title">Share of stock-days inside the expected range, by severity</h2>
    <div class="chart" style="max-width:560px"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Within-range rate by severity band">
      <line x1="0" x2="${W}" y1="${H - pb}" y2="${H - pb}" stroke="var(--grid)"/>${bars}</svg></div>
    <div class="table-wrap" style="margin-top:12px"><table><thead><tr><th>Severity</th><th class="num">Stock-days</th><th class="num">Within range</th><th class="num">Actual ÷ expected range</th></tr></thead><tbody>
      ${bands.map((b) => `<tr><td>${b.label}</td><td class="num">${b.n}</td><td class="num">${b.within == null ? "—" : Math.round(b.within * 100) + "%"}</td><td class="num">${b.ratio == null ? "—" : b.ratio.toFixed(2)}</td></tr>`).join("")}
    </tbody></table></div>
    <p class="muted small">"Actual ÷ expected range" near 1.0 means the ranges are well calibrated. Above 1 means moves were bigger than expected.</p>
    <h2 class="section-title">Daily detail</h2>
    <div class="table-wrap"><table><thead><tr>${["Date", "Symbol", "Sev", "Direction", "Prev close", "Expected low", "Expected high", "Actual low", "Actual high", "Close", "In range", "Dir. hit"].map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>
      ${recent.map((d) => `<tr><td>${esc(d.trading_date)}</td><td>${esc(d.symbol)}</td><td class="num">${esc(d.severity)}</td><td>${esc(d.direction)}</td><td class="num">${esc(d.prev_close)}</td><td class="num">${esc(d.expected_low)}</td><td class="num">${esc(d.expected_high)}</td><td class="num">${esc(d.actual_low)}</td><td class="num">${esc(d.actual_high)}</td><td class="num">${esc(d.actual_close)}</td><td>${d.within_range === "True" ? "✓ yes" : "✗ no"}</td><td>${d.direction_hit === "True" ? "✓" : d.direction_hit === "False" ? "✗" : "—"}</td></tr>`).join("")}
    </tbody></table></div>`;
  state.accuracyLoaded = true;
}

/* ---------------- wiring ---------------- */
async function loadDate(date) {
  try {
    state.digest = await getJSON(`data/digests/${date}.json`);
  } catch {
    state.digest = await getJSON("data/latest.json");
  }
  populateFilterOptions();
  renderDigest();
}

function bind() {
  $("dateSelect").addEventListener("change", (e) => loadDate(e.target.value));
  $("capChips").addEventListener("click", (e) => {
    const c = e.target.closest("[data-cap]"); if (!c) return;
    const f = state.filters.caps; f.has(c.dataset.cap) ? f.delete(c.dataset.cap) : f.add(c.dataset.cap);
    renderChips(); renderDigest();
  });
  $("dirChips").addEventListener("click", (e) => {
    const c = e.target.closest("[data-dir]"); if (!c) return;
    const f = state.filters.dirs; f.has(c.dataset.dir) ? f.delete(c.dataset.dir) : f.add(c.dataset.dir);
    renderChips(); renderDigest();
  });
  $("indexToggle").addEventListener("change", (e) => { state.filters.showIndex = e.target.checked; renderDigest(); });
  $("sevRange").addEventListener("input", (e) => { state.filters.minSev = +e.target.value; $("sevOut").textContent = e.target.value; renderDigest(); });
  $("sectorSelect").addEventListener("change", (e) => { state.filters.sector = e.target.value; renderDigest(); });
  $("eventSelect").addEventListener("change", (e) => { state.filters.event = e.target.value; renderDigest(); });
  $("search").addEventListener("input", (e) => { state.filters.q = e.target.value.trim(); renderDigest(); });
  $("resetFilters").addEventListener("click", () => {
    state.filters = defaultFilters();
    $("indexToggle").checked = true; $("sevRange").value = 1; $("sevOut").textContent = "1"; $("search").value = "";
    renderChips(); populateFilterOptions(); renderDigest();
  });
  $("portfolioFile").addEventListener("change", async (e) => {
    const file = e.target.files[0]; if (!file) return;
    const st = $("portfolioStatus");
    try {
      state.holdings = loadPortfolio(await file.text());
      st.className = "small ok"; st.textContent = `${Object.keys(state.holdings).length} holdings loaded (in this tab only).`;
      $("clearPortfolio").hidden = false;
    } catch (err) {
      st.className = "small err"; st.textContent = `Could not read the CSV: ${err.message}`;
    }
    e.target.value = "";
    renderDigest();
  });
  $("clearPortfolio").addEventListener("click", () => {
    state.holdings = {}; $("portfolioStatus").textContent = ""; $("clearPortfolio").hidden = true; renderDigest();
  });
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => { x.classList.toggle("active", x === t); x.setAttribute("aria-selected", x === t); });
    const v = t.dataset.view;
    $("view-digest").hidden = v !== "digest"; $("view-accuracy").hidden = v !== "accuracy";
    $("sidebar").style.display = v === "digest" ? "" : "none";
    if (v === "accuracy") renderAccuracy();
  }));
  $("filtersToggle").addEventListener("click", () => {
    const sb = $("sidebar"); sb.classList.toggle("open");
    $("filtersToggle").setAttribute("aria-expanded", sb.classList.contains("open"));
  });
}

async function init() {
  bind(); renderChips();
  try {
    try { state.dates = await getJSON("data/digests/index.json"); } catch { state.dates = []; }
    if (!state.dates.length) {
      const latest = await getJSON("data/latest.json");
      state.dates = [latest.trading_date];
    }
    $("dateSelect").innerHTML = state.dates.map((d) => `<option value="${esc(d)}">${esc(fmtDay(d))}</option>`).join("");
    await loadDate(state.dates[0]);
  } catch (err) {
    $("items").innerHTML = `<div class="empty">No digest has been generated yet. The pipeline runs every trading morning at 08:00 IST.</div>`;
    console.error(err);
  }
}
init();

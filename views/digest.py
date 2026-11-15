"""Streamlit front end. Reads the pre-built digest JSON only; never calls the LLM."""
from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
IST = ZoneInfo("Asia/Kolkata")

EVENT_LABELS = {
    "earnings": "Earnings", "corporate_action": "Corporate action", "order_win": "Order win",
    "management_change": "Management change", "regulatory": "Regulatory (SEBI/RBI)",
    "macro_data": "Macro data", "monetary_policy": "Monetary policy", "global_cues": "Global cues",
    "commodity_currency": "Commodity / currency", "block_bulk_deal": "Block / bulk deal",
    "rating_change": "Rating change", "legal_penalty": "Legal / penalty", "other": "Other",
}
DIRECTION = {"bullish": ("▲", "Bullish", "#1a7f4b"), "bearish": ("▼", "Bearish", "#c0392b"),
             "mixed": ("◆", "Mixed", "#8a6d1f"), "uncertain": ("●", "Uncertain", "#5f6b7a")}
UP, DOWN, BAND = "#1a7f4b", "#c0392b", "rgba(64, 120, 200, 0.18)"
DISCLAIMER = ("**Not investment advice.** This digest is generated automatically from public headlines "
              "and an AI model's judgement, which can be wrong. Expected ranges are statistical "
              "estimates from recent volatility, not price predictions. Always read the original "
              "source and do your own research before trading.")


# ---------------------------------------------------------------- data
@st.cache_data(ttl=600)
def available_dates(_mtime: float) -> list[str]:
    return sorted((p.stem for p in (DATA / "digests").glob("????-??-??.json")), reverse=True)


@st.cache_data(ttl=600)
def load_digest(day: str, _mtime: float) -> dict:
    return json.loads((DATA / "digests" / f"{day}.json").read_text(encoding="utf-8"))


def mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def stock_bucket(s: dict) -> str:
    if s.get("is_index"):
        return "Index"
    return "Penny" if s.get("is_penny") else s.get("cap_bucket", "Unknown")


def fmt_inr(x: float) -> str:
    sign = "-" if x < 0 else "+"
    x = abs(x)
    if x >= 1e7:
        return f"{sign}₹{x / 1e7:.2f} cr"
    if x >= 1e5:
        return f"{sign}₹{x / 1e5:.2f} L"
    return f"{sign}₹{x:,.0f}"


def parse_portfolio(raw: bytes) -> dict[str, float]:
    df = pd.read_csv(io.BytesIO(raw))
    cols = {c.lower().strip(): c for c in df.columns}
    sym = next((cols[c] for c in ("symbol", "ticker", "tradingsymbol", "instrument", "stock") if c in cols), None)
    qty = next((cols[c] for c in ("qty", "quantity", "shares", "qty.", "units") if c in cols), None)
    if sym is None or qty is None:
        raise ValueError("CSV needs a 'symbol' column and a 'quantity' column")
    out: dict[str, float] = {}
    for s, q in zip(df[sym], df[qty]):
        s = str(s).strip().upper().removesuffix(".NS").removesuffix("-EQ")
        try:
            out[s] = out.get(s, 0.0) + float(q)
        except (TypeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------- chart
def range_chart(stock: dict, trading_date: str) -> go.Figure | None:
    er = stock.get("expected_range")
    if not er or not er.get("history"):
        return None
    h = pd.DataFrame(er["history"])
    fig = go.Figure(go.Candlestick(
        x=h["date"], open=h["open"], high=h["high"], low=h["low"], close=h["close"],
        increasing=dict(line=dict(color=UP, width=1), fillcolor=UP),
        decreasing=dict(line=dict(color=DOWN, width=1), fillcolor=DOWN),
        name="Daily OHLC", showlegend=False))
    # expected range for the digest session, drawn as a band at the right edge
    fig.add_trace(go.Bar(
        x=[f"{trading_date} (expected)"], y=[er["expected_high"] - er["expected_low"]],
        base=[er["expected_low"]], marker=dict(color=BAND, line=dict(color="#4078c8", width=1)),
        width=0.6, name="Expected range", showlegend=False,
        hovertemplate=(f"Expected range<br>Low ₹{er['expected_low']:,.2f}<br>"
                       f"High ₹{er['expected_high']:,.2f}<extra></extra>")))
    fig.add_hline(y=er["prev_close"], line=dict(color="#8893a2", width=1, dash="dot"),
                  annotation_text=f"Prev close {er['prev_close']:,.2f}",
                  annotation_position="top left", annotation_font_size=11)
    fig.update_layout(height=260, margin=dict(l=8, r=8, t=24, b=8), xaxis_rangeslider_visible=False,
                      hovermode="x unified", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      title=dict(text=f"{stock['symbol']} — last {len(h)} sessions + expected range",
                                 font=dict(size=13)))
    fig.update_xaxes(type="category", showgrid=False, tickangle=-45, nticks=8)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)", zeroline=False)
    return fig


# ---------------------------------------------------------------- card
def stock_line(s: dict, holdings: dict[str, float]) -> str:
    er = s.get("expected_range")
    tag = stock_bucket(s)
    label = f"**{s['symbol']}**" + ("" if s.get("is_index") else f" · {tag}")
    if s.get("relation") == "indirect":
        label += " · indirect"
    if not er:
        return label + " · range n/a"
    text = (f"{label} · prev ₹{er['prev_close']:,.2f} → expected ₹{er['expected_low']:,.2f}"
            f" – ₹{er['expected_high']:,.2f} (±{er['expected_move_pct'] / 2:.1f}%)")
    q = holdings.get(s["symbol"])
    if q:
        down = (er["expected_low"] - er["prev_close"]) * q
        up = (er["expected_high"] - er["prev_close"]) * q
        text += f" · 📌 your {q:,.0f} shares: {fmt_inr(down)} / {fmt_inr(up)}"
    return text


def render_card(it: dict, trading_date: str, holdings: dict[str, float], key: str) -> None:
    icon, dlabel, dcolor = DIRECTION[it["direction"]]
    held = [s["symbol"] for s in it["stocks"] if s["symbol"] in holdings]
    with st.container(border=True):
        c1, c2 = st.columns([1, 11], vertical_alignment="top")
        with c1:
            st.markdown(
                f"<div style='text-align:center;font-size:1.6rem;font-weight:700;line-height:1'>{it['severity']}"
                f"<div style='font-size:.65rem;font-weight:400;opacity:.7'>severity</div></div>",
                unsafe_allow_html=True)
        with c2:
            pin = "📌 " if held else ""
            st.markdown(f"{pin}**#{it['rank']} · [{it['title']}]({it['url']})**")
            when = datetime.fromisoformat(it["published_at"]).astimezone(IST).strftime("%d %b %H:%M")
            cov = f" · covered by {it['coverage_count']} outlets" if it["coverage_count"] > 1 else ""
            st.markdown(
                f"<span style='color:{dcolor};font-weight:600'>{icon} {dlabel}</span> · "
                f"{EVENT_LABELS.get(it['event_type'], it['event_type'])} · {it['scope'].replace('_', ' ')}"
                f" · {it['source']} · {when} IST{cov}", unsafe_allow_html=True)
            st.write(it["why_it_matters"])
            for s in it["stocks"][:3]:
                st.markdown("- " + stock_line(s, holdings))
            with st.expander("Details, charts and sources"):
                if it.get("snippet"):
                    st.caption(it["snippet"])
                st.markdown(f"Surprise: **{it['surprise_factor']}** · Confidence: **{it['confidence']}**"
                            f" · Sectors: {', '.join(it['affected_sectors']) or '—'}")
                for s in it["stocks"][3:]:
                    st.markdown("- " + stock_line(s, holdings))
                if it.get("unmapped_companies"):
                    st.caption("Not matched to an NSE symbol: " + ", ".join(it["unmapped_companies"]))
                charts = [s for s in it["stocks"] if s.get("expected_range")]
                for s in charts[:3]:
                    fig = range_chart(s, trading_date)
                    if fig:
                        st.plotly_chart(fig, width="stretch", key=f"{key}-{s['symbol']}",
                                        config={"displayModeBar": False})
                links = it.get("covered_by") or []
                if len(links) > 1:
                    st.markdown("Also covered by: " + " · ".join(
                        f"[{c['source']}]({c['url']})" for c in links[:8]))


# ---------------------------------------------------------------- page
dates = available_dates(mtime(DATA / "latest.json"))
st.title("📈 Nifty News Volatility Digest")
if not dates:
    st.info("No digest has been generated yet. The pipeline runs every trading morning at 08:00 IST.")
    st.markdown(DISCLAIMER)
    st.stop()

with st.sidebar:
    st.header("Filters")
    day = st.selectbox("Digest date", dates, index=0,
                       format_func=lambda d: datetime.strptime(d, "%Y-%m-%d").strftime("%a %d %b %Y"))
digest = load_digest(day, mtime(DATA / "digests" / f"{day}.json"))
items: list[dict] = digest["items"]
all_sectors = sorted({s for it in items for s in it["affected_sectors"]})
all_events = sorted({it["event_type"] for it in items})

with st.sidebar:
    caps = st.multiselect("Market cap", ["Large", "Mid", "Small", "Penny", "Unknown"],
                          default=["Large", "Mid", "Small", "Penny", "Unknown"])
    show_index = st.toggle("Include index / macro news", value=True)
    min_sev = st.slider("Minimum severity", 1, 10, 1)
    dirs = st.multiselect("Direction", list(DIRECTION), default=list(DIRECTION),
                          format_func=lambda d: DIRECTION[d][1])
    sectors = st.multiselect("Sector", all_sectors, placeholder="All sectors")
    events = st.multiselect("Event type", all_events, placeholder="All event types",
                            format_func=lambda e: EVENT_LABELS.get(e, e))
    query = st.text_input("Search headline or symbol", placeholder="e.g. HDFCBANK, results")

    st.divider()
    st.subheader("My portfolio")
    st.caption("Optional. CSV with `symbol` and `quantity` columns (Zerodha/Groww exports work). "
               "Kept only in this browser session; never saved on the server.")
    up = st.file_uploader("Upload holdings CSV", type=["csv"], label_visibility="collapsed")
    if up is not None:
        try:
            st.session_state["holdings"] = parse_portfolio(up.getvalue())
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not read the CSV: {exc}")
    holdings: dict[str, float] = st.session_state.get("holdings", {})
    if holdings:
        st.success(f"{len(holdings)} holdings loaded")
        if st.button("Clear portfolio"):
            st.session_state.pop("holdings", None)
            st.rerun()


def passes(it: dict) -> bool:
    if it["severity"] < min_sev or it["direction"] not in dirs:
        return False
    if sectors and not set(sectors) & set(it["affected_sectors"]):
        return False
    if events and it["event_type"] not in events:
        return False
    if query:
        q = query.lower()
        hay = " ".join([it["title"], it["snippet"]] + [s["symbol"] + " " + s["name"] for s in it["stocks"]]).lower()
        if q not in hay:
            return False
    eq = [s for s in it["stocks"] if not s.get("is_index")]
    if not eq:
        return show_index if (it["scope"] != "single_stock" or it["stocks"]) else "Unknown" in caps
    return any(stock_bucket(s) in caps for s in eq) or (show_index and it["scope"] == "index")


# header
gen = datetime.fromisoformat(digest["generated_at"]).astimezone(IST)
tday = datetime.strptime(digest["trading_date"], "%Y-%m-%d")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Trading session", tday.strftime("%a %d %b"))
m2.metric("Updated (IST)", gen.strftime("%d %b %H:%M"))
m3.metric("Items", len(items))
if digest.get("india_vix") is not None:
    chg = digest.get("india_vix_change_pct")
    m4.metric("India VIX", f"{digest['india_vix']:.2f}", None if chg is None else f"{chg:+.2f}%",
              delta_color="inverse")
if digest.get("market_mood"):
    st.info("  \n".join(f"**{line}**" if i == 0 else line for i, line in enumerate(digest["market_mood"])),
            icon="🧭")
if digest.get("events"):
    st.markdown("**Today's events:** " + " · ".join(
        f"{e['name']}" + (" ⚠️" if e.get("importance") == "high" else "") for e in digest["events"]))

shown = [it for it in items if passes(it)]
if holdings:
    shown.sort(key=lambda it: (not any(s["symbol"] in holdings for s in it["stocks"]), it["rank"]))
top_n = 10
top, rest = shown[:top_n], shown[top_n:]
st.caption(f"Showing {len(shown)} of {len(items)} items · news since "
           f"{datetime.fromisoformat(digest['window_start']).astimezone(IST).strftime('%a %d %b %H:%M')} IST")

if not shown:
    st.warning("No items match these filters.")
if top:
    st.subheader("🔥 Top 10 must-read" + (" (your holdings pinned first)" if holdings else ""))
    for it in top:
        render_card(it, digest["trading_date"], holdings, key=f"t{it['id']}")
if rest:
    st.subheader("More news")
    for it in rest:
        render_card(it, digest["trading_date"], holdings, key=f"r{it['id']}")

with st.expander("Pipeline details"):
    src = pd.DataFrame(digest.get("source_stats", {})).T
    if not src.empty:
        st.dataframe(src, width="stretch")
    st.json(digest.get("pipeline_stats", {}), expanded=False)

st.divider()
st.markdown(DISCLAIMER)

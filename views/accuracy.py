"""How well did yesterday's expected ranges and directions hold up?"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DATA = Path(__file__).resolve().parent.parent / "data"
st.title("🎯 Accuracy tracker")
st.caption("Each morning the pipeline compares earlier digests with what actually happened in that "
           "session: did the stock stay inside its expected range, and did it close in the predicted "
           "direction (bullish/bearish items only)?")


@st.cache_data(ttl=600)
def load(_mtime: float) -> pd.DataFrame:
    return pd.read_csv(DATA / "evaluation.csv")


path = DATA / "evaluation.csv"
if not path.exists():
    st.info("No evaluations yet. They appear after the first trading session following a digest.")
    st.stop()

df = load(path.stat().st_mtime)
df["within_range"] = df["within_range"].astype(str).str.lower() == "true"
dirs = df[df["direction_hit"].notna() & (df["direction_hit"].astype(str) != "")].copy()
dirs["hit"] = dirs["direction_hit"].astype(str).str.lower() == "true"

c1, c2, c3, c4 = st.columns(4)
c1.metric("Sessions evaluated", df["trading_date"].nunique())
c2.metric("Stock-days", len(df))
c3.metric("Stayed within expected range", f"{df['within_range'].mean():.0%}")
c4.metric("Direction correct", f"{dirs['hit'].mean():.0%}" if len(dirs) else "—",
          help="Bullish = closed above previous close; bearish = closed below.")

st.subheader("By severity")
df["sev_band"] = pd.cut(df["severity"], [0, 3, 6, 8, 10], labels=["1-3", "4-6", "7-8", "9-10"])
by = df.groupby("sev_band", observed=True).agg(
    stock_days=("symbol", "size"), within_range=("within_range", "mean"),
    avg_actual_vs_expected=("range_ratio", "mean")).reset_index()
fig = go.Figure(go.Bar(x=by["sev_band"].astype(str), y=by["within_range"] * 100,
                       marker=dict(color="#4078c8", cornerradius=4),
                       text=[f"{v:.0%}" for v in by["within_range"]], textposition="outside",
                       hovertemplate="Severity %{x}<br>Within range %{y:.0f}%<extra></extra>"))
fig.update_layout(height=280, margin=dict(l=8, r=8, t=8, b=8), yaxis=dict(range=[0, 110], title="% within range",
                  gridcolor="rgba(128,128,128,0.15)"), xaxis=dict(title="Severity band"),
                  plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
st.dataframe(by.style.format({"within_range": "{:.0%}", "avg_actual_vs_expected": "{:.2f}"}),
             width="stretch", hide_index=True)
st.caption("`avg_actual_vs_expected` = actual high-low range ÷ expected range. Around 1.0 means the "
           "ranges are well calibrated; above 1 means moves were bigger than expected.")

st.subheader("Daily detail")
st.dataframe(df.sort_values(["trading_date", "rank"], ascending=[False, True]),
             width="stretch", hide_index=True)
st.divider()
st.markdown("**Not investment advice.** Expected ranges are statistical estimates, not predictions.")

"""Streamlit entry point: `streamlit run app.py`. Reads pre-built JSON only; never calls the LLM."""
import streamlit as st

st.set_page_config(page_title="Nifty News Volatility Digest", page_icon="📈", layout="wide")
nav = st.navigation([
    st.Page("views/digest.py", title="Today's digest", icon="📈", default=True),
    st.Page("views/accuracy.py", title="Accuracy", icon="🎯"),
])
nav.run()

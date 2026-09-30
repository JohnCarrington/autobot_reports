#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
streamlit_dashboard.py — READ-ONLY snapshot dashboard (multi-symbol)

- Polls snapshot.json
- Shows all symbols simultaneously
- Tabs: Overview + per-symbol
"""

import json
import time
from pathlib import Path
from datetime import datetime

import streamlit as st
from streamlit_autorefresh import st_autorefresh

SNAPSHOT_PATH = Path("/opt/tradingbot/snapshot.json")
REFRESH_MS = 1000

st.set_page_config(
    page_title="AutoBot Dashboard (Read-Only)",
    layout="wide",
)

st.title("📊 AutoBot — Read-Only Dashboard")

st_autorefresh(interval=REFRESH_MS, key="snapshot_refresh")

st.sidebar.header("Connection Status")

if not SNAPSHOT_PATH.exists():
    st.sidebar.warning("Snapshot file not found")
    st.info("Waiting for AutoBot snapshot…")
    st.stop()

try:
    snapshot = json.loads(SNAPSHOT_PATH.read_text())
except Exception as e:
    st.sidebar.error("Snapshot read error")
    st.error(str(e))
    st.stop()

ts = snapshot.get("ts")
symbols = snapshot.get("symbols", {})

if not symbols:
    st.info("No symbol data yet.")
    st.stop()

age = time.time() - ts if ts else None
if age is not None:
    st.sidebar.success(f"Last update: {age:.1f}s ago")

tabs = ["Overview"] + list(symbols.keys())
tab_objs = st.tabs(tabs)

# -------------------- OVERVIEW --------------------
with tab_objs[0]:
    cols = st.columns(len(symbols))
    for col, (sym, data) in zip(cols, symbols.items()):
        with col:
            st.subheader(sym)
            st.metric("Mid Price", data["price"]["mid"])
            st.metric("Signal", data["decision"]["signal"])
            st.caption(f"Reason: {data['decision']['reason']}")

# -------------------- PER SYMBOL --------------------
for i, (sym, data) in enumerate(symbols.items(), start=1):
    with tab_objs[i]:
        st.subheader(sym)
        c1, c2, c3 = st.columns(3)
        c1.metric("Mid Price", data["price"]["mid"])
        c2.metric("Signal", data["decision"]["signal"])
        c3.metric("Status", data["decision"]["reason"])

        if ts:
            st.caption(
                f"Snapshot time: {datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')}"
            )

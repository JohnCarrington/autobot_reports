#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sentinel Dashboard — Real-Time AI Command Center
------------------------------------------------

Displays:
    • Candle charts (1m, 5m, 1h)
    • Live Sentinel neural signals
    • AiBrain internals (confidence, regime, size multiplier)
    • Neural Meta-Controller diagnostics
    • Meta-Learning state
    • Experience buffer statistics
    • Live tick panel
    • Active trade panel
    • A/B testing panel
    • Rollback safety panel
    • Resource usage panel
"""

import json
import time
import psutil
import pandas as pd
import streamlit as st
from pathlib import Path


# ============================================================
# FILE PATHS
# ============================================================
BASE = Path("/opt/tradingbot")
CACHE = BASE / "cache"
STATE = BASE / "sentinel_state.json"
META = BASE / "meta_learning_state.json"
NMC = BASE / "nmc_state.json"
BUFFER = BASE / "experience_buffer_stats.json"
AB_R = BASE / "optimizer/ab_results.json"
ROLLBACK = BASE / "optimizer/rollback.log"
LOGFILE = BASE / "sentinel.log"

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="Sentinel AI Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🧠 Sentinel AI Dashboard")
st.caption("Real-Time Neural Trading Supervisor")


# ============================================================
# Sidebar Controls
# ============================================================
st.sidebar.header("Refresh")
r = st.sidebar.slider("Refresh Interval (seconds)", 1, 10, 2)
st.sidebar.info("Dashboard auto-refreshes using Streamlit rerun mode.")


# ============================================================
# Helper loaders
# ============================================================
def load_json(path):
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except:
        return None

def load_candles(name):
    fp = CACHE / name
    if not fp.exists():
        return None
    try:
        df = pd.read_csv(fp, parse_dates=["timestamp"])
        return df.sort_values("timestamp")
    except:
        return None


# ============================================================
# 1. Live Sentinel State
# ============================================================
st.header("🟢 Sentinel Live State")

state = load_json(STATE)

if not state:
    st.warning("Sentinel state not available.")
else:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Symbol", state.get("symbol", "—"))
    col2.metric("Signal", state.get("signal", "NONE"))
    col3.metric("Confidence", f"{state.get('confidence', 0):.3f}")
    col4.metric("Size Multiplier", f"{state.get('size_mult', 1.0):.2f}")

    st.write("### Decision Debug")
    st.json(state.get("debug", {}))


# ============================================================
# 2. Candle Panels (1m/5m/1h)
# ============================================================
st.header("📊 Candle Charts")

df1 = load_candles("hist_1m.csv")
df5 = load_candles("hist_5m.csv")
df1h = load_candles("hist_1h.csv")

colA, colB, colC = st.columns(3)

if df1 is not None:
    colA.subheader("1m")
    colA.line_chart(df1.set_index("timestamp")["close"])

if df5 is not None:
    colB.subheader("5m")
    colB.line_chart(df5.set_index("timestamp")["close"])

if df1h is not None:
    colC.subheader("1h")
    colC.line_chart(df1h.set_index("timestamp")["close"])


# ============================================================
# 3. Neural Meta-Controller
# ============================================================
st.header("🧩 Neural Meta-Controller (NMC)")

nmc = load_json(NMC)
if not nmc:
    st.info("NMC state unavailable.")
else:
    c1, c2, c3 = st.columns(3)
    c1.metric("Regime Now", nmc.get("regime_now", "—"))
    c2.metric("Regime Future", nmc.get("regime_future", "—"))
    c3.metric("Action Policy", nmc.get("action", "—"))

    st.write("### Neural Outputs")
    st.json(nmc)


# ============================================================
# 4. Meta-Learning Layer
# ============================================================
st.header("🧠 Meta-Learning State")

ml = load_json(META)
if not ml:
    st.info("Meta-learning state unavailable.")
else:
    st.subheader("Weights")
    st.json(ml.get("W", {}))

    st.subheader("Confidence")
    st.json(ml.get("C", {}))

    st.subheader("Q-Values")
    st.json(ml.get("Q", {}))

    st.subheader("Recent Updates")
    st.json(ml.get("history", [])[-10:])


# ============================================================
# 5. Experience Buffer
# ============================================================
st.header("📚 Experience Buffer")

buf = load_json(BUFFER)
if not buf:
    st.info("Buffer stats unavailable.")
else:
    st.metric("Stored Experiences", buf.get("count", 0))
    st.metric("Capacity", buf.get("capacity", 0))


# ============================================================
# 6. Trade Manager Panel
# ============================================================
st.header("💼 Active Trade")

if state and "trade" in state:
    st.json(state["trade"])
else:
    st.info("No active trade.")


# ============================================================
# 7. A/B Testing Panel
# ============================================================
st.header("🧬 A/B Testing")

abr = load_json(AB_R)
if not abr:
    st.info("A/B results unavailable.")
else:
    col1, col2 = st.columns(2)
    col1.metric("Model A PnL", abr["A"]["pnl"])
    col1.metric("Model A DD", abr["A"]["drawdown"])
    col1.metric("Trades A", len(abr["A"]["trades"]))

    col2.metric("Model B PnL", abr["B"]["pnl"])
    col2.metric("Model B DD", abr["B"]["drawdown"])
    col2.metric("Trades B", len(abr["B"]["trades"]))

    st.write("### Recent Trades A")
    st.write(abr["A"]["trades"][-10:])

    st.write("### Recent Trades B")
    st.write(abr["B"]["trades"][-10:])


# ============================================================
# 8. Rollback Status
# ============================================================
st.header("⏪ Rollback Status")

if ROLLBACK.exists():
    with ROLLBACK.open() as f:
        lines = f.readlines()[-15:]
        st.code("".join(lines))
else:
    st.info("No rollback log found.")


# ============================================================
# 9. Resource Usage
# ============================================================
st.header("🖥 System Health")

cpu = psutil.cpu_percent(interval=0.4)
mem = psutil.virtual_memory()

c1, c2 = st.columns(2)
c1.metric("CPU Load", f"{cpu}%")
c2.metric("Memory Usage", f"{mem.percent}%")


# ============================================================
# 10. Sentinel Log (live tail)
# ============================================================
st.header("📜 Sentinel Log (tail)")

if LOGFILE.exists():
    with LOGFILE.open() as f:
        lines = f.readlines()[-40:]
        st.code("".join(lines))
else:
    st.info("No Sentinel logs found.")


# ============================================================
# 🔥 REGIME HEATMAP
# ============================================================
st.header("🔥 Regime Heatmap (Last 100 Intervals)")

# Load regime history stored by Sentinel
REGIME_HISTORY = BASE / "regime_history.json"
rh = load_json(REGIME_HISTORY)

if not rh or "history" not in rh:
    st.info("Regime history unavailable — Sentinel has not collected enough data yet.")
else:
    hist = rh["history"][-100:]  # last 100 entries
    dfR = pd.DataFrame(hist)

    # Map regimes to numeric for heatmap
    mapping = {
        "TREND": 3,
        "VOLATILE": 2,
        "RANGE": 1,
        "CALM": 0
    }
    dfR["regime_code"] = dfR["regime"].map(mapping)

    # Colour palette for regime categories
    import seaborn as sns
    import matplotlib.pyplot as plt

    import matplotlib.colors as mcolors
    cmap = mcolors.ListedColormap([
        "#1f77b4",  # CALM (blue)
        "#2ca02c",  # RANGE (green)
        "#ff7f0e",  # VOLATILE (orange)
        "#d62728",  # TREND (red)
    ])

    # Plot regime strip
    fig, ax = plt.subplots(figsize=(10, 1.8))
    sns.heatmap(
        dfR[["regime_code"]].T,
        cmap=cmap,
        cbar=False,
        linewidths=0.0,
        xticklabels=False,
        yticklabels=[]
    )
    ax.set_title("Regime Strip — Last 100 Evaluations")
    st.pyplot(fig)

    # Regime counts
    st.write("### Regime Distribution")
    st.bar_chart(dfR["regime"].value_counts())

    # Regime-confidence map (if provided)
    if "confidence" in dfR.columns:
        st.write("### Regime Confidence Over Time")
        st.line_chart(dfR.set_index("timestamp")["confidence"])


# ============================================================
# Auto-refresh
# ============================================================
time.sleep(r)
st.rerun()
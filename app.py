import streamlit as st
import pandas as pd
import numpy as np
from data_fetcher import DataPipeline
from engine_pro import InstitutionalEngine
from trading_manager import RiskManager
from database_manager import init_db, engine as db_engine
from sqlalchemy import text
from datetime import datetime, timezone

# 1. INITIALIZE DATABASE TABLES
init_db()

st.set_page_config(
    page_title="🛡️ Institutional NSE Swing Platform",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- SIDEBAR: SCANNER CONTROL ---
st.sidebar.title("Trading Controls")
st.sidebar.markdown("---")
st.sidebar.warning("🛡️ **Stealth Mode Active**: Scanning is done in secure chunks to prevent API blocking. A full scan takes 8-10 minutes.")

if st.sidebar.button("🚀 Run Full NSE500 Scan"):
    today = datetime.now(timezone.utc).date()
    symbols = DataPipeline.get_nse500_symbols()

    # 1. FETCH REGIME DATA (Indices)
    with st.spinner("Analyzing Market Context (Nifty)..."):
        mkt_df = DataPipeline.fetch_market_data("^NSEI")
        mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")

    # 2. SYNTHETIC FALLBACK (Prevents engine crash if Yahoo blocks Index data)
    if mkt_df is None:
        st.warning("⚠️ Market Index API blocked. Using synthetic baseline for analysis.")
        dates = pd.date_range(end=datetime.now(), periods=300)
        mkt_df = pd.DataFrame({
            'Close': [23000 + (x * 1.2) for x in range(300)],
            'High': [23100]*300, 'Low': [22900]*300, 'Volume': [0]*300
        }, index=dates)
    
    if mid_df is None:
        mid_df = mkt_df

    # 3. START STEALTH CHUNKED DOWNLOAD
    st.info(f"Downloading {len(symbols)} symbols in secure batches...")
    all_data = DataPipeline.fetch_batch_data(symbols)

    if all_data is None or all_data.empty:
        st.error("❌ Yahoo Finance is currently rejecting this server's IP. Please wait 15 minutes and try again.")
    else:
        progress = st.progress(0)
        status_text = st.empty()
        final_data_batch = []

        # 4. ANALYSIS LOOP (Pure RAM processing)
        # We loop through symbols locally to maintain UI progress
        for i, sym in enumerate(symbols):
            ticker_sym = f"{sym}.NS"
            try:
                # Extract individual stock from batch results
                if ticker_sym not in all_data.columns.get_level_values(0):
                    continue

                df = all_data[ticker_sym].dropna()

                if len(df) >= 150:
                    # Run Scoring Engine
                    engine = InstitutionalEngine(df, mkt_df, mid_df)
                    score, setup_type, explanation = engine.get_contextual_score()

                    # Filter for High Probability Setups (70+)
                    if score >= 70:
                        # Dynamic ATR Risk Check
                        levels = RiskManager.get_levels(df)
                        if levels:
                            final_data_batch.append({
                                "symbol": sym,
                                "scan_date": today,
                                "score": int(score),
                                "setup_type": setup_type,
                                "market_regime": "BULLISH" if score > 75 else "NEUTRAL",
                                "entry": float(levels['entry']),
                                "stop_loss": float(levels['stop_loss']),
                                "target_1": float(levels['t1']),
                                "target_2": float(levels['t2']),
                                "target_3": float(levels['t3']),
                                "risk_reward": float(levels['rr']),
                                "explanation": str(explanation)
                            })
            except Exception:
                continue

            if i % 10 == 0:
                status_text.text(f"Institutional Analysis: {sym} ({i+1}/{len(symbols)})...")
                progress.progress((i + 1) / len(symbols))

        # 5. DIRECT ATOMIC DATABASE SYNC
        if final_data_batch:
            # We use text-based SQL to ensure 'ON CONFLICT' is respected perfectly
            insert_query = text("""
                INSERT INTO pro_scans_v2
                (symbol, scan_date, score, setup_type, market_regime, entry, stop_loss, target_1, target_2, target_3, risk_reward, explanation)
                VALUES (:symbol, :scan_date, :score, :setup_type, :market_regime, :entry, :stop_loss, :target_1, :target_2, :target_3, :risk_reward, :explanation)
                ON CONFLICT ON CONSTRAINT _symbol_date_uc DO NOTHING
            """)
            try:
                with db_engine.begin() as conn:
                    # Clear today's cache and replace with fresh scan results
                    conn.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = :d"), {"d": today})
                    conn.execute(insert_query, final_data_batch)
                
                status_text.text("✅ Scan Complete!")
                st.sidebar.success(f"Discovered {len(final_data_batch)} Institutional Setups.")
                st.balloons()
            except Exception as e:
                st.error(f"Database sync failed: {e}")
        else:
            status_text.text("✅ Scan Complete — no stocks passed the Elite threshold today.")

# --- MAIN UI: DASHBOARD ---
st.title("🛡️ Institutional NSE Swing Platform")
st.markdown("**Market Status:** Real-time analysis of volatility, trend alignment, and institutional accumulation.")

try:
    today = datetime.now(timezone.utc).date()

    with db_engine.connect() as conn:
        # Fetch today's results sorted by score
        rows = conn.execute(
            text("SELECT * FROM pro_scans_v2 WHERE scan_date = :d ORDER BY score DESC"),
            {"d": today}
        ).mappings().all()

        # If today is empty (market closed or scan not run), show latest historical
        if not rows:
            st.info("No new setups scanned for today yet. Showing latest results from previous sessions.")
            rows = conn.execute(
                text("SELECT * FROM pro_scans_v2 ORDER BY scan_date DESC, score DESC LIMIT 30")
            ).mappings().all()

    if rows:
        st.subheader(f"🎯 Top Opportunities ({len(rows)})")

        for res in rows:
            is_elite = res['score'] >= 85
            header = f"{'🔥 [ELITE]' if is_elite else '⭐'} {res['symbol']} | Score: {res['score']}/100 | {res['setup_type']}"

            with st.expander(header):
                col1, col2, col3 = st.columns([1, 1, 1.5])

                with col1:
                    st.write("**📍 Trade Levels**")
                    st.code(f"Entry: ₹{res['entry']}")
                    st.code(f"Stop:  ₹{res['stop_loss']}")
                    st.write(f"**Risk/Reward:** {res['risk_reward']}")

                with col2:
                    st.write("**🎯 Profit Targets**")
                    st.success(f"Target 1: ₹{res['target_1']}")
                    st.success(f"Target 2: ₹{res['target_2']}")
                    st.success(f"Target 3: ₹{res['target_3']}")

                with col3:
                    st.write("**📊 Analysis Factors**")
                    points = res['explanation'].split(" | ")
                    for p in points:
                        st.write(f"✅ {p}")
                    st.caption(f"Scan Date: {res['scan_date']} | Market: {res['market_regime']}")
    else:
        st.warning("The database is currently empty. Trigger a 'Full Scan' from the sidebar to begin.")

except Exception as e:
    st.error(f"UI Loading Error: {e}")

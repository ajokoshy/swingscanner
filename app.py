import streamlit as st
import pandas as pd
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
st.sidebar.info("Scanner analyzed the Nifty 500 universe using an institutional multi-factor model.")

if st.sidebar.button("🚀 Run Full NSE500 Scan"):
    today = datetime.now(timezone.utc).date()
    symbols = DataPipeline.get_nse500_symbols()

    # 1. FETCH REGIME DATA (Resilient with 3 retries)
    mkt_df = DataPipeline.fetch_market_data("^NSEI")
    mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")

    # Fallback if Yahoo blips on Index data to prevent crash
    if mkt_df is None:
        st.warning("⚠️ Nifty 50 data unavailable. Using neutral regime score.")
        mkt_df = pd.DataFrame({
            'Close': [23000]*300, 'High': [23100]*300, 'Low': [22900]*300, 
            'Volume': [0]*300, 'Open': [23000]*300
        })
    if mid_df is None:
        mid_df = mkt_df

    # 2. START CHUNKED DOWNLOAD (The Anti-Block Fix)
    st.info(f"Downloading batch data for {len(symbols)} stocks in Institutional Chunks...")
    all_data = DataPipeline.fetch_batch_data(symbols)

    if all_data is None or all_data.empty:
        st.error("❌ Batch download failed. Yahoo Finance is currently unresponsive to this IP.")
    else:
        progress = st.progress(0)
        status_text = st.empty()
        final_data_batch = []

        # 3. ANALYSIS LOOP — pure RAM, no DB contact inside loop for speed
        for i, sym in enumerate(symbols):
            ticker_sym = f"{sym}.NS"
            try:
                # Safe Multi-Index Extraction from the batch result
                if ticker_sym not in all_data.columns.get_level_values(0):
                    continue

                df = all_data[ticker_sym].dropna()

                if len(df) >= 150:
                    # Institutional Grade Engine (100pt model)
                    engine = InstitutionalEngine(df, mkt_df, mid_df)
                    score, setup_type, explanation = engine.get_contextual_score()

                    if score >= 70:
                        # ATR-Based Risk Management (RR > 2.0 check)
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

            if i % 20 == 0:
                status_text.text(f"Analyzing {sym} ({i+1}/{len(symbols)})...")
                progress.progress((i + 1) / len(symbols))

        # 4. ATOMIC DATABASE UPDATE
        if final_data_batch:
            insert_query = text("""
                INSERT INTO pro_scans_v2
                (symbol, scan_date, score, setup_type, market_regime, entry, stop_loss, target_1, target_2, target_3, risk_reward, explanation)
                VALUES (:symbol, :scan_date, :score, :setup_type, :market_regime, :entry, :stop_loss, :target_1, :target_2, :target_3, :risk_reward, :explanation)
                ON CONFLICT ON CONSTRAINT _symbol_date_uc DO NOTHING
            """)
            try:
                # Wipe today's existing data first then batch insert (Safe Idempotent Pattern)
                with db_engine.begin() as conn:
                    conn.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = :d"), {"d": today})
                    conn.execute(insert_query, final_data_batch)
                
                status_text.text(f"✅ Scan Complete! Found {len(final_data_batch)} setups.")
                st.sidebar.success(f"Saved {len(final_data_batch)} setups for {today}")
                st.balloons()
            except Exception as e:
                st.error(f"Database save failed: {e}")
        else:
            status_text.text("✅ Scan Complete — no setups met the threshold today.")

# --- MAIN UI: DASHBOARD ---
st.title("🛡️ Institutional NSE Swing Platform")
st.markdown("**Market Status:** Analysis based on latest Nifty 50 Close.")

try:
    today = datetime.now(timezone.utc).date()

    with db_engine.connect() as conn:
        # Try today's results first
        rows = conn.execute(
            text("SELECT * FROM pro_scans_v2 WHERE scan_date = :d ORDER BY score DESC"),
            {"d": today}
        ).mappings().all()

        # Fallback to latest historical results
        if not rows:
            st.info("No new setups scanned today yet. Showing latest historical results.")
            rows = conn.execute(
                text("SELECT * FROM pro_scans_v2 ORDER BY scan_date DESC, score DESC LIMIT 20")
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
                    st.success(f"T1: ₹{res['target_1']}")
                    st.success(f"T2: ₹{res['target_2']}")
                    st.success(f"T3: ₹{res['target_3']}")

                with col3:
                    st.write("**📊 Analysis Factors**")
                    points = res['explanation'].split(" | ")
                    for p in points:
                        st.write(f"✅ {p}")
                    st.caption(f"Scanned: {res['scan_date']} | Market: {res['market_regime']}")
    else:
        st.warning("The database is currently empty. Please trigger a 'Full Scan' from the sidebar.")

except Exception as e:
    st.error(f"Dashboard error: {e}")

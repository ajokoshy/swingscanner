import streamlit as st
import pandas as pd
from data_fetcher import DataPipeline
from engine_pro import InstitutionalEngine
from trading_manager import RiskManager
from database_manager import init_db, engine as db_engine
from sqlalchemy import text
from datetime import datetime, timezone

# Initialize Database
init_db()

st.set_page_config(page_title="🛡️ Institutional NSE Swing Platform", layout="wide")

# --- SIDEBAR ---
st.sidebar.title("Trading Controls")
if st.sidebar.button("🚀 Run Full NSE500 Scan"):
    today = datetime.now(timezone.utc).date()
    symbols = DataPipeline.get_nse500_symbols()

    # Resilient Fetch for Indices
    mkt_df = DataPipeline.fetch_market_data("^NSEI")
    mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")

    # Fallback if Yahoo blips on Index data
    if mkt_df is None:
        st.warning("⚠️ Nifty 50 data unavailable. Using neutral regime score.")
        mkt_df = pd.DataFrame({'Close': [100]*300, 'High': [101]*300, 'Low': [99]*300, 'Volume': [0]*300, 'Open': [100]*300})
    if mid_df is None:
        mid_df = mkt_df

    st.info(f"Downloading batch data for {len(symbols)} stocks...")
    all_data = DataPipeline.fetch_batch_data(symbols)

    if all_data is None or all_data.empty:
        st.error("Batch download failed. Yahoo Finance is unresponsive.")
    else:
        progress = st.progress(0)
        status_text = st.empty()
        final_data_batch = []

        for i, sym in enumerate(symbols):
            ticker_sym = f"{sym}.NS"
            try:
                if ticker_sym not in all_data.columns.get_level_values(0):
                    continue
                
                df = all_data[ticker_sym].dropna()
                if len(df) >= 150:
                    engine = InstitutionalEngine(df, mkt_df, mid_df)
                    score, setup_type, explanation = engine.get_contextual_score()
                    
                    if score >= 70:
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
                status_text.text(f"Analyzing {sym}... ({i+1}/{len(symbols)})")
                progress.progress((i + 1) / len(symbols))

        # YOUR MOD: The safe Batch Insert pattern
        if final_data_batch:
            insert_query = text("""
                INSERT INTO pro_scans_v2
                (symbol, scan_date, score, setup_type, market_regime, entry, stop_loss, target_1, target_2, target_3, risk_reward, explanation)
                VALUES (:symbol, :scan_date, :score, :setup_type, :market_regime, :entry, :stop_loss, :target_1, :target_2, :target_3, :risk_reward, :explanation)
                ON CONFLICT ON CONSTRAINT _symbol_date_uc DO NOTHING
            """)
            try:
                with db_engine.begin() as conn: # 'begin' handles auto-commit/rollback
                    conn.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = :d"), {"d": today})
                    conn.execute(insert_query, final_data_batch)
                status_text.text(f"✅ Scan Complete! Found {len(final_data_batch)} setups.")
                st.sidebar.success(f"Saved {len(final_data_batch)} setups for {today}")
                st.balloons()
            except Exception as e:
                st.error(f"Database error: {e}")
        else:
            status_text.text("✅ Scan Complete — no setups met the threshold today.")

# --- DASHBOARD UI ---
st.title("🛡️ Institutional NSE Swing Platform")
st.markdown("**Market Status:** Analysis based on latest Nifty 50 Close.")

try:
    today = datetime.now(timezone.utc).date()
    with db_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM pro_scans_v2 WHERE scan_date = :d ORDER BY score DESC"),
            {"d": today}
        ).mappings().all()

        if not rows:
            st.info("No new setups scanned today. Showing latest historical results.")
            rows = conn.execute(
                text("SELECT * FROM pro_scans_v2 ORDER BY scan_date DESC, score DESC LIMIT 20")
            ).mappings().all()

    if rows:
        st.subheader(f"🎯 Top Opportunities ({len(rows)})")
        for res in rows:
            is_elite = res['score'] >= 85
            header = f"{'🔥 [ELITE]' if is_elite else '⭐'} {res['symbol']} | Score: {res['score']}/100 | {res['setup_type']}"

            # YOUR MOD: Institutional Layout
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
        st.warning("Database empty. Run scan from sidebar.")
except Exception as e:
    st.error(f"UI Error: {e}")

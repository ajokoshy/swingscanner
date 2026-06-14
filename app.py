import streamlit as st
from data_fetcher import DataPipeline
from engine_pro import InstitutionalEngine
from trading_manager import RiskManager
from database_manager import init_db, engine as db_engine
from sqlalchemy import text
from datetime import datetime, timezone

init_db()

st.set_page_config(page_title="🛡️ Institutional NSE Swing Platform", layout="wide")

st.sidebar.title("Trading Controls")
if st.sidebar.button("🚀 Run Full NSE500 Scan"):
    today = datetime.now(timezone.utc).date()
    symbols = DataPipeline.get_nse500_symbols()

    # Fetch Indices
    mkt_df = DataPipeline.fetch_market_data("^NSEI") # Nifty 50
    mid_df = DataPipeline.fetch_market_data("^NSEMDCP50") # Midcap

    # If Nifty fails, create a dummy dataframe so the scanner doesn't crash
    if mkt_df is None:
        st.warning("⚠️ Nifty 50 data unavailable. Regime scores will be set to Neutral.")
        # Create a dummy DF with columns needed by the engine
        mkt_df = pd.DataFrame({'Close': [100]*300, 'High': [101]*300, 'Low': [99]*300, 'Volume': [0]*300})
    
    if mid_df is None:
        mid_df = mkt_df # Use Nifty 50 as fallback for midcap

    st.info(f"Downloading batch data for {len(symbols)} stocks...")
    all_data = DataPipeline.fetch_batch_data(symbols)

    if all_data is None or all_data.empty:
        st.error("Batch download failed. Yahoo Finance is currently unresponsive.")
    else:
        progress = st.progress(0)
        status_text = st.empty()
        final_data_batch = []

        for i, sym in enumerate(symbols):
            ticker_sym = f"{sym}.NS"
            try:
                # Safe Multi-Index Extraction
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
                status_text.text(f"Analyzing {sym} ({i+1}/{len(symbols)})...")
                progress.progress((i + 1) / len(symbols))

        if final_data_batch:
            insert_query = text("""
                INSERT INTO pro_scans_v2
                (symbol, scan_date, score, setup_type, market_regime, entry, stop_loss, target_1, target_2, target_3, risk_reward, explanation)
                VALUES (:symbol, :scan_date, :score, :setup_type, :market_regime, :entry, :stop_loss, :target_1, :target_2, :target_3, :risk_reward, :explanation)
                ON CONFLICT ON CONSTRAINT _symbol_date_uc DO NOTHING
            """)
            try:
                with db_engine.begin() as conn:
                    conn.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = :d"), {"d": today})
                    conn.execute(insert_query, final_data_batch)
                status_text.text(f"✅ Scan Complete! Found {len(final_data_batch)} setups.")
                st.sidebar.success(f"Saved: {len(final_data_batch)} setups")
                st.balloons()
            except Exception as e:
                st.error(f"Database save failed: {e}")
        else:
            status_text.text("✅ Scan Complete — no new high-score setups found today.")

# --- DASHBOARD REMAINS SAME AS YOURS ---
st.title("🛡️ Institutional NSE Swing Platform")
# ... (rest of the dashboard code from your attached file)

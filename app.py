import streamlit as st
from data_fetcher import DataPipeline
from engine_pro import ScoringEngine
from trading_manager import RiskManager
from database_manager import init_db, SessionLocal, ProScanResult # Reusing your previous DB setup

st.set_page_config(page_title="NSE Pro Swing", layout="wide")

def analyze_stock(symbol):
    # 1. Fetch
    df = DataPipeline.get_clean_data(symbol)
    if df is None:
        return st.error(f"Ineligible Stock: {symbol} (Low Liquidity or Insufficient Data)")

    # 2. Process
    df = ScoringEngine.apply_indicators(df)
    score, factors = ScoringEngine.calculate_score(df)
    
    # 3. Setup
    setup = RiskManager.get_trade_setup(df)
    
    if setup:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Institutional Score", f"{score}/100")
            st.write(f"**Classification:** {'ELITE' if score >= 85 else 'STRONG' if score >= 70 else 'MONITOR'}")
            for f in factors: st.write(f"✅ {f}")
            
        with col2:
            st.subheader("Trade Setup (ATR-Adjusted)")
            st.write(f"**Entry:** ₹{setup['entry']}")
            st.write(f"**Stop Loss:** ₹{setup['stop_loss']} (Vol: {setup['atr']})")
            st.write(f"**Target 1 (2R):** ₹{setup['target1']}")
            st.write(f"**Target 2 (3R):** ₹{setup['target2']}")
            st.write(f"**Target 3 (5R):** ₹{setup['target3']}")
            st.info(f"Risk Reward Ratio: {setup['rr']}")
    else:
        st.warning("No valid trade setup found for this stock.")

# UI Logic
st.title("🛡️ Production NSE Swing Engine")
sym = st.text_input("Enter Symbol", "RELIANCE")
if sym:
    analyze_stock(sym)

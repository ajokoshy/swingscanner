import os
import sys
import traceback
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from sqlalchemy import text
from data_fetcher import DataPipeline
from engine_pro import InstitutionalEngine
from trading_manager import RiskManager
from database_manager import init_db, engine as db_engine

# --- NO ORM IMPORTS HERE (ProScanResult/SessionLocal removed to prevent auto-flush) ---

def send_email(setups):
    sender_email = os.getenv("EMAIL_USER")
    sender_password = os.getenv("EMAIL_PASS")
    receiver_email = os.getenv("RECEIVER_EMAIL")
    if not setups:
        print("No new setups found today. Skipping email.")
        return

    msg = MIMEMultipart()
    msg['Subject'] = f"🚀 NSE Swing Report: {datetime.now(timezone.utc).date()}"
    msg['From'] = f"NSE Pro Scanner <{sender_email}>"
    msg['To'] = receiver_email

    html = f"<h3>Institutional Swing Setups Found Today ({len(setups)})</h3>"
    html += "<table border='1' style='border-collapse: collapse; width: 100%; font-family: sans-serif;'>"
    html += "<tr style='background-color: #004a99; color: white;'><th>Symbol</th><th>Score</th><th>Setup</th><th>Entry</th><th>Target 1</th><th>RR</th></tr>"
    
    # setups are now dictionaries from raw SQL result
    for s in setups:
        html += f"<tr><td style='padding: 8px;'><b>{s['symbol']}</b></td><td style='padding: 8px;'>{s['score']}</td><td style='padding: 8px;'>{s['setup_type']}</td><td style='padding: 8px;'>₹{s['entry']}</td><td style='padding: 8px;'>₹{s['target_1']}</td><td style='padding: 8px;'>{s['risk_reward']}</td></tr>"
    html += "</table><p>Visit Dashboard for full ATR levels and detailed analysis.</p>"
    msg.attach(MIMEText(html, 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print("✅ Email report sent successfully.")
    except Exception as e:
        print(f"❌ Email failed: {e}")

def run_automation():
    try:
        # Step 0: Initialize Tables (Safe)
        init_db()
        today = datetime.now(timezone.utc).date()
        
        # 1. NUCLEAR MAINTENANCE: Purge the problematic dates causing crashes
        # We talk directly to the Engine, bypassing the Session layer entirely.
        print(f"Maintenance: Purging database collisions for {today} and June 13th...")
        with db_engine.connect() as conn:
            # Clear today's date AND the problematic June 13th date from your logs
            conn.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = '2026-06-13'"))
            conn.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = :d"), {"d": today})
            conn.commit()

        # 2. DATA ACQUISITION
        symbols = DataPipeline.get_nse500_symbols()
        # Fast filter for junk symbols
        symbols = [s.strip() for s in symbols if s and not s.startswith("DUMMY")]
        
        mkt_df = DataPipeline.fetch_market_data("^NSEI")
        mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")
        all_data = DataPipeline.fetch_batch_data(symbols)
        
        if mkt_df is None:
            raise Exception("Regime data (Nifty 50) unavailable.")

        print(f"🚀 Analyzing {len(symbols)} symbols in memory...")
        batch_to_save = []

        # 3. ANALYSIS LOOP (Pure Python dictionaries - No DB objects)
        for sym in symbols:
            try:
                ticker_sym = f"{sym}.NS"
                if ticker_sym not in all_data.columns.get_level_values(0):
                    continue
                
                df = all_data[ticker_sym].dropna()
                if len(df) >= 150:
                    engine = InstitutionalEngine(df, mkt_df, mid_df)
                    score, setup_type, explanation = engine.get_contextual_score()
                    
                    if score >= 70:
                        levels = RiskManager.get_levels(df)
                        if levels:
                            # 4. STORE IN SIMPLE DICTIONARY (Bypasses SQLAlchemy Session tracking)
                            batch_to_save.append({
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

        # 5. RAW SQL BULK INSERT (The final fix for IntegrityError)
        if batch_to_save:
            print(f"Directly saving {len(batch_to_save)} setups via Raw SQL...")
            # 'ON CONFLICT DO NOTHING' ensures we never crash even if DELETE failed
            insert_sql = text("""
                INSERT INTO pro_scans_v2 
                (symbol, scan_date, score, setup_type, market_regime, entry, stop_loss, target_1, target_2, target_3, risk_reward, explanation)
                VALUES (:symbol, :scan_date, :score, :setup_type, :market_regime, :entry, :stop_loss, :target_1, :target_2, :target_3, :risk_reward, :explanation)
                ON CONFLICT (symbol, scan_date) DO NOTHING
            """)
            
            with db_engine.connect() as conn:
                # SQLAlchemy Core handles the entire list as a single high-speed transaction
                conn.execute(insert_sql, batch_to_save)
                conn.commit()
        
        # 6. RAW SQL FETCH FOR EMAIL
        print("Finalizing results for email report...")
        with db_engine.connect() as conn:
            fetch_sql = text("SELECT symbol, score, setup_type, entry, target_1, risk_reward FROM pro_scans_v2 WHERE scan_date = :d ORDER BY score DESC")
            final_list = conn.execute(fetch_sql, {"d": today}).mappings().all()
        
        print(f"✅ Success. Found {len(final_list)} setups.")
        send_email(final_list)
        
    except Exception:
        print("--- FATAL SYSTEM ERROR ---")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    run_automation()

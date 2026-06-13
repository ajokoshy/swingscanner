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

def send_email(setups):
    sender_email = os.getenv("EMAIL_USER")
    sender_password = os.getenv("EMAIL_PASS")
    receiver_email = os.getenv("RECEIVER_EMAIL")
    if not setups:
        print("No new elite setups found. Email skipped.")
        return

    msg = MIMEMultipart()
    msg['Subject'] = f"🚀 NSE Swing Report: {datetime.now(timezone.utc).date()}"
    msg['From'] = f"NSE Pro Scanner <{sender_email}>"
    msg['To'] = receiver_email

    html = f"<h3>Institutional Swing Setups Found Today ({len(setups)})</h3>"
    html += "<table border='1' style='border-collapse: collapse; width: 100%; font-family: sans-serif;'>"
    html += "<tr style='background-color: #004a99; color: white;'><th>Symbol</th><th>Score</th><th>Setup</th><th>Entry</th><th>Target 1</th><th>RR</th></tr>"
    
    # Sort setups by score for the email
    sorted_setups = sorted(setups, key=lambda x: x['score'], reverse=True)
    
    for s in sorted_setups:
        html += f"<tr><td style='padding: 8px;'><b>{s['symbol']}</b></td><td style='padding: 8px;'>{s['score']}</td><td style='padding: 8px;'>{s['setup_type']}</td><td style='padding: 8px;'>₹{s['entry']}</td><td style='padding: 8px;'>₹{s['target_1']}</td><td style='padding: 8px;'>{s['risk_reward']}</td></tr>"
    html += "</table><p>Visit your dashboard for full ATR analysis and Stop Loss levels.</p>"
    
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
        # Initialize Tables
        init_db()
        today = datetime.now(timezone.utc).date()
        
        # 1. NUCLEAR MAINTENANCE: Clear database collisions using Direct Engine Access
        # This bypasses the SQLAlchemy Session entirely to avoid 'Autoflush' errors.
        print(f"Purging database collisions for {today} and June 13th...")
        with db_engine.connect() as conn:
            conn.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = :d OR scan_date = '2026-06-13'"), {"d": today})
            conn.commit()

        # 2. DATA ACQUISITION
        symbols = DataPipeline.get_nse500_symbols()
        # Filter symbols
        symbols = [s.strip() for s in symbols if s and not s.startswith("DUMMY")]
        
        mkt_df = DataPipeline.fetch_market_data("^NSEI")
        mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")
        
        if mkt_df is None:
            raise Exception("Regime data (Nifty 50) unavailable.")

        all_data = DataPipeline.fetch_batch_data(symbols)
        
        print(f"🚀 Analyzing {len(symbols)} stocks in memory...")
        final_data_batch = []

        # 3. ANALYSIS LOOP (Pure Python - No DB calls here)
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
                            # CREATE RAW DICTIONARY (Bypass ORM Class)
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

        # 4. DIRECT BATCH INSERT (High Speed + Atomic)
        if final_data_batch:
            print(f"Saving {len(final_data_batch)} setups to database...")
            # Using raw SQL string ensures PostgreSQL handles the 'ON CONFLICT' rule correctly
            insert_query = text("""
                INSERT INTO pro_scans_v2 
                (symbol, scan_date, score, setup_type, market_regime, entry, stop_loss, target_1, target_2, target_3, risk_reward, explanation)
                VALUES (:symbol, :scan_date, :score, :setup_type, :market_regime, :entry, :stop_loss, :target_1, :target_2, :target_3, :risk_reward, :explanation)
                ON CONFLICT (symbol, scan_date) DO NOTHING
            """)
            
            with db_engine.connect() as conn:
                # Executes the entire list as a single high-speed transaction
                conn.execute(insert_query, final_data_batch)
                conn.commit()
        
        # 5. SEND EMAIL
        print(f"✅ Success. Scanned {len(symbols)} stocks. Found {len(final_data_batch)} setups.")
        send_email(final_data_batch)
        
    except Exception:
        print("--- CRITICAL SYSTEM ERROR ---")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    run_automation()

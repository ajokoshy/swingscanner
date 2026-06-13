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
from database_manager import init_db, engine as db_engine, ProScanResult, SessionLocal

def send_email(setups):
    sender_email = os.getenv("EMAIL_USER")
    sender_password = os.getenv("EMAIL_PASS")
    receiver_email = os.getenv("RECEIVER_EMAIL")
    if not setups:
        print("No new setups to report today.")
        return

    msg = MIMEMultipart()
    msg['Subject'] = f"🚀 NSE Swing Report: {datetime.now(timezone.utc).date()}"
    msg['From'] = f"NSE Pro Scanner <{sender_email}>"
    msg['To'] = receiver_email

    html = f"<h3>Institutional Swing Setups Found ({len(setups)})</h3>"
    html += "<table border='1' style='border-collapse: collapse; width: 100%; font-family: sans-serif;'>"
    html += "<tr style='background-color: #004a99; color: white;'><th>Symbol</th><th>Score</th><th>Setup</th><th>Entry</th><th>Target 1</th><th>RR</th></tr>"
    for s in setups:
        html += f"<tr><td style='padding: 8px;'><b>{s.symbol}</b></td><td style='padding: 8px;'>{s.score}</td><td style='padding: 8px;'>{s.setup_type}</td><td style='padding: 8px;'>₹{s.entry}</td><td style='padding: 8px;'>₹{s.target_1}</td><td style='padding: 8px;'>{s.risk_reward}</td></tr>"
    html += "</table><p>Visit Dashboard for full ATR levels.</p>"
    msg.attach(MIMEText(html, 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print("✅ Email sent.")
    except Exception as e:
        print(f"❌ Email failed: {e}")

def run_automation():
    try:
        init_db()
        today = datetime.now(timezone.utc).date()
        
        # 1. NUCLEAR CLEANUP: Bypass Session and talk directly to the Engine
        # This wipes the 'June 13' collision and today's data to ensure a fresh start
        print("Maintenance: Purging database collisions...")
        with db_engine.connect() as conn:
            conn.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = '2026-06-13'"))
            conn.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = :d"), {"d": today})
            conn.commit()

        # 2. DATA ACQUISITION
        symbols = DataPipeline.get_nse500_symbols()
        symbols = [s.strip() for s in symbols if s and not s.startswith("DUMMY")]
        mkt_df = DataPipeline.fetch_market_data("^NSEI")
        mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")
        all_data = DataPipeline.fetch_batch_data(symbols)
        
        print(f"🚀 Analyzing {len(symbols)} stocks...")
        batch_to_insert = []

        # 3. ANALYSIS LOOP (Pure Python - No database contact here)
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
                            # Create a simple DICTIONARY. 
                            # Do NOT use ProScanResult() here to avoid SQLAlchemy tracking.
                            batch_to_insert.append({
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

        # 4. DIRECT BATCH UPSERT (The fix for both Speed and UniqueViolation)
        if batch_to_insert:
            print(f"Saving {len(batch_to_insert)} setups directly to database...")
            insert_query = text("""
                INSERT INTO pro_scans_v2 
                (symbol, scan_date, score, setup_type, market_regime, entry, stop_loss, target_1, target_2, target_3, risk_reward, explanation)
                VALUES (:symbol, :scan_date, :score, :setup_type, :market_regime, :entry, :stop_loss, :target_1, :target_2, :target_3, :risk_reward, :explanation)
                ON CONFLICT (symbol, scan_date) DO NOTHING
            """)
            
            with db_engine.connect() as conn:
                # SQLAlchemy Core handles the list of dictionaries as a bulk insert
                conn.execute(insert_query, batch_to_insert)
                conn.commit()
        
        # 5. FETCH FOR EMAIL
        # Use a fresh, clean session just for reading
        read_db = SessionLocal()
        final_setups = read_db.query(ProScanResult).filter_by(scan_date=today).order_by(ProScanResult.score.desc()).all()
        read_db.close()
        
        print(f"✅ Scan Complete. Found {len(final_setups)} setups.")
        send_email(final_setups)
        
    except Exception:
        print("--- CRITICAL SYSTEM ERROR ---")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    run_automation()

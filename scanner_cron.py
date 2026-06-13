import os
import sys
import traceback
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from sqlalchemy import text, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert # Required for Upsert
from data_fetcher import DataPipeline
from engine_pro import InstitutionalEngine
from trading_manager import RiskManager
from database_manager import init_db, SessionLocal, ProScanResult

def send_email(setups):
    sender_email = os.getenv("EMAIL_USER")
    sender_password = os.getenv("EMAIL_PASS")
    receiver_email = os.getenv("RECEIVER_EMAIL")

    if not setups:
        print("No new elite setups found today.")
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
    html += "</table><p>Visit Dashboard for Full Analysis.</p>"
    
    msg.attach(MIMEText(html, 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print("Email sent successfully.")
    except Exception as e:
        print(f"Email failed: {e}")

def run_automation():
    db = SessionLocal()
    try:
        init_db()
        
        # 1. CLEANUP STUCK DATA (Ensures June 13th collisions are cleared)
        db.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = '2026-06-13'"))
        db.commit()

        symbols = DataPipeline.get_nse500_symbols()
        mkt_df = DataPipeline.fetch_market_data("^NSEI")
        mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")
        
        if mkt_df is None:
            raise Exception("Regime data unavailable.")

        all_data = DataPipeline.fetch_batch_data(symbols)
        today = datetime.now(timezone.utc).date()
        print(f"Scanning {len(symbols)} stocks for {today}...")

        for sym in symbols:
            try:
                ticker_sym = f"{sym}.NS"
                if ticker_sym not in all_data.columns.get_level_values(0):
                    continue
                
                df = all_data[ticker_sym].dropna()
                if len(df) >= 200:
                    engine = InstitutionalEngine(df, mkt_df, mid_df)
                    score, setup_type, explanation = engine.get_contextual_score()
                    
                    if score >= 70:
                        levels = RiskManager.get_levels(df)
                        if levels:
                            # 2. DATA DICTIONARY (No Class instantiation)
                            data_values = {
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
                            }

                            # 3. DIRECT CORE UPSERT (Bypasses ORM Session)
                            # This specific command handles duplicates at the Database level
                            stmt = pg_insert(ProScanResult).values(data_values)
                            stmt = stmt.on_conflict_do_nothing(index_elements=['symbol', 'scan_date'])
                            
                            db.execute(stmt)
                            db.commit() # Atomic commit for every stock
            except Exception as e:
                db.rollback()
                continue

        # 4. FETCH RESULTS FROM DB TO EMAIL
        final_setups = db.query(ProScanResult).filter_by(scan_date=today).order_by(ProScanResult.score.desc()).all()
        send_email(final_setups)
        
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    run_automation()

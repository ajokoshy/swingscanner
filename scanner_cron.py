import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from data_fetcher import DataPipeline
from engine_pro import InstitutionalEngine
from trading_manager import RiskManager
from database_manager import init_db, SessionLocal, ProScanResult

def send_email(setups):
    sender_email = os.getenv("EMAIL_USER")
    sender_password = os.getenv("EMAIL_PASS")
    receiver_email = os.getenv("RECEIVER_EMAIL")

    if not setups:
        print("No setups found today. Skipping email.")
        return

    msg = MIMEMultipart()
    msg['Subject'] = f"🚀 NSE Swing Report: {datetime.now().date()}"
    msg['From'] = f"NSE Pro Scanner <{sender_email}>"
    msg['To'] = receiver_email

    # Build HTML Table
    html = "<h3>Top Institutional Swing Setups</h3><table border='1'><tr><th>Symbol</th><th>Score</th><th>Setup</th><th>Entry</th><th>Target 1</th></tr>"
    for s in setups:
        html += f"<tr><td>{s['symbol']}</td><td>{s['score']}</td><td>{s['type']}</td><td>{s['entry']}</td><td>{s['t1']}</td></tr>"
    html += "</table><p>Open your Dashboard for full details.</p>"
    
    msg.attach(MIMEText(html, 'html'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())

def run_automation():
    init_db()
    symbols = DataPipeline.get_nse500_symbols()
    mkt_df = DataPipeline.fetch_market_data("^NSEI")
    mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")
    
    all_data = DataPipeline.fetch_batch_data(symbols)
    db = SessionLocal()
    email_setups = []
    today = datetime.now(timezone.utc).date()

    for sym in symbols:
        try:
            ticker_sym = f"{sym}.NS"
            if ticker_sym not in all_data.columns.get_level_values(0): continue
            df = all_data[ticker_sym].dropna()
            
            if len(df) >= 200:
                engine = InstitutionalEngine(df, mkt_df, mid_df)
                score, setup_type, explanation = engine.get_contextual_score()
                
                if score >= 75: # Only email high-quality setups
                    levels = RiskManager.get_levels(df)
                    if levels:
                        # Save to DB
                        res = ProScanResult(
                            symbol=sym, score=score, setup_type=setup_type,
                            market_regime="BULLISH", entry=levels['entry'],
                            stop_loss=levels['stop_loss'], target_1=levels['t1'],
                            target_2=levels['t2'], target_3=levels['t3'],
                            risk_reward=levels['rr'], explanation=explanation
                        )
                        db.add(res)
                        email_setups.append({'symbol': sym, 'score': score, 'type': setup_type, 'entry': levels['entry'], 't1': levels['t1']})
        except: continue

    db.commit()
    db.close()
    send_email(email_setups)

if __name__ == "__main__":
    run_automation()
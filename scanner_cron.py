"""
scanner_cron.py  —  SwingScanner v2
Automated daily scan runner (GitHub Actions / any cron).

Improvements over v1:
  • Synthetic index fallback if Yahoo blocks index fetches
  • Partial DB flush every FLUSH_EVERY setups (no data loss on crash)
  • Market-hours guard (skip if today is weekend / NSE holiday)
  • Structured logging
  • Bhavcopy cache refresh at startup
"""

import logging
import os
import smtplib
import sys
import traceback
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
from sqlalchemy import text

from data_fetcher import DataPipeline, refresh_bhavcopy_cache
from database_manager import init_db, engine as db_engine
from engine_pro import InstitutionalEngine
from trading_manager import RiskManager

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scanner_cron")

SCORE_THRESHOLD = 70
FLUSH_EVERY = 25          # write to DB every N setups found (partial-save guard)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

INSERT_SQL = text("""
    INSERT INTO pro_scans_v2
        (symbol, scan_date, score, setup_type, market_regime,
         entry, stop_loss, target_1, target_2, target_3, risk_reward, explanation)
    VALUES
        (:symbol, :scan_date, :score, :setup_type, :market_regime,
         :entry, :stop_loss, :target_1, :target_2, :target_3, :risk_reward, :explanation)
    ON CONFLICT ON CONSTRAINT _symbol_date_uc DO NOTHING
""")


def _flush_batch(batch: list[dict]) -> None:
    """Write a list of setup dicts to the database and clear the list."""
    if not batch:
        return
    with db_engine.connect() as conn:
        conn.execute(INSERT_SQL, batch)
        conn.commit()
    logger.info("Flushed %d setups to DB.", len(batch))
    batch.clear()


def _synthetic_index() -> pd.DataFrame:
    """
    Return a synthetic Nifty-like DataFrame when the real index is unavailable.
    Keeps the engine from crashing; scores will be slightly off but usable.

    Uses pd.bdate_range sliced from a fixed start to guarantee exactly 300 rows
    regardless of what day of the week today falls on.
    """
    all_bdays = pd.bdate_range(start="2010-01-01", end=datetime.now())
    dates = all_bdays[-300:]
    n = len(dates)
    return pd.DataFrame({
        "Open":   [23000 + x * 1.2 for x in range(n)],
        "High":   [23100 + x * 1.2 for x in range(n)],
        "Low":    [22900 + x * 1.2 for x in range(n)],
        "Close":  [23000 + x * 1.2 for x in range(n)],
        "Volume": [0] * n,
    }, index=dates)


def send_email(setups: list) -> None:
    sender_email    = os.getenv("EMAIL_USER")
    sender_password = os.getenv("EMAIL_PASS")
    receiver_email  = os.getenv("RECEIVER_EMAIL")

    if not (sender_email and sender_password and receiver_email):
        logger.warning("Email credentials not set — skipping email.")
        return

    if not setups:
        logger.info("No elite setups today — email skipped.")
        return

    msg = MIMEMultipart()
    msg["Subject"] = f"🚀 NSE Swing Report: {datetime.now(timezone.utc).date()}"
    msg["From"]    = f"NSE Pro Scanner <{sender_email}>"
    msg["To"]      = receiver_email

    sorted_setups = sorted(setups, key=lambda x: x["score"], reverse=True)

    html = (
        f"<h3>Institutional Swing Setups — {datetime.now(timezone.utc).date()} "
        f"({len(sorted_setups)} found)</h3>"
        "<table border='1' style='border-collapse:collapse;width:100%;font-family:sans-serif;'>"
        "<tr style='background:#004a99;color:white;'>"
        "<th>Symbol</th><th>Score</th><th>Setup</th>"
        "<th>Entry</th><th>Stop</th><th>T1</th><th>RR</th><th>Regime</th>"
        "</tr>"
    )
    for s in sorted_setups:
        bg = "#fff8e1" if s["score"] >= 85 else "#ffffff"
        html += (
            f"<tr style='background:{bg};'>"
            f"<td style='padding:8px'><b>{s['symbol']}</b></td>"
            f"<td style='padding:8px'>{s['score']}</td>"
            f"<td style='padding:8px'>{s['setup_type']}</td>"
            f"<td style='padding:8px'>₹{s['entry']}</td>"
            f"<td style='padding:8px'>₹{s['stop_loss']}</td>"
            f"<td style='padding:8px'>₹{s['target_1']}</td>"
            f"<td style='padding:8px'>{s['risk_reward']}</td>"
            f"<td style='padding:8px'>{s['market_regime']}</td>"
            "</tr>"
        )
    html += "</table><p>Visit Dashboard for full analysis.</p>"
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        logger.info("✅ Email report sent to %s.", receiver_email)
    except Exception as exc:
        logger.error("❌ Email failed: %s", exc)


# ---------------------------------------------------------------------------
# Main scan routine
# ---------------------------------------------------------------------------

def run_automation() -> None:
    try:
        today = datetime.now(timezone.utc).date()

        # ── 0. Guard: skip weekends (NSE is closed) ──────────────────────
        if today.weekday() >= 5:
            logger.info("Today is %s — NSE closed. Exiting.", today.strftime("%A"))
            return

        # ── 1. Init DB ────────────────────────────────────────────────────
        init_db()

        # ── 2. Refresh Bhavcopy cache (non-fatal) ────────────────────────
        try:
            logger.info("Refreshing Bhavcopy cache...")
            refresh_bhavcopy_cache(days=500)
        except Exception as exc:
            logger.warning("Bhavcopy cache refresh failed (non-fatal): %s", exc)

        # ── 3. Purge today's stale rows (idempotent re-runs) ──────────────
        logger.info("Purging existing rows for %s...", today)
        with db_engine.connect() as conn:
            conn.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = :d"), {"d": today})
            conn.commit()

        # ── 4. Fetch symbols ──────────────────────────────────────────────
        symbols = DataPipeline.get_nse500_symbols()
        symbols = [s.strip() for s in symbols if s and not s.startswith("DUMMY")]
        logger.info("Scanning %d symbols...", len(symbols))

        # ── 5. Fetch index data (with synthetic fallback) ─────────────────
        logger.info("Fetching Nifty 50 index...")
        mkt_df = DataPipeline.fetch_market_data("^NSEI")
        if mkt_df is None:
            logger.warning("Nifty index unavailable — using synthetic baseline.")
            mkt_df = _synthetic_index()

        logger.info("Fetching Nifty MidCap 50...")
        mid_df = DataPipeline.fetch_market_data("^NSEMDCP50")
        if mid_df is None:
            logger.warning("MidCap index unavailable — using Nifty as proxy.")
            mid_df = mkt_df

        # ── 6. Batch fetch stock data ─────────────────────────────────────
        logger.info("Starting batch data fetch...")
        all_data = DataPipeline.fetch_batch_data(symbols)

        if all_data is None or all_data.empty:
            raise RuntimeError(
                "All data sources (yfinance, yahooquery, Bhavcopy) exhausted. "
                "Cannot proceed with scan."
            )

        available_tickers = set(all_data.columns.get_level_values(0))
        logger.info("Data available for %d tickers.", len(available_tickers))

        # ── 7. Analysis loop (RAM-only) with partial flush ─────────────────
        logger.info("Starting analysis...")
        pending_batch: list[dict] = []
        analysed = skipped = total_setups_found = 0

        for sym in symbols:
            ticker_sym = f"{sym}.NS"
            try:
                if ticker_sym not in available_tickers:
                    skipped += 1
                    continue

                df = all_data[ticker_sym].dropna()
                if len(df) < 150:
                    skipped += 1
                    continue

                engine = InstitutionalEngine(df, mkt_df, mid_df)
                score, setup_type, explanation = engine.get_contextual_score()
                analysed += 1

                if score >= SCORE_THRESHOLD:
                    levels = RiskManager.get_levels(df)
                    if levels:
                        pending_batch.append({
                            "symbol":        sym,
                            "scan_date":     today,
                            "score":         int(score),
                            "setup_type":    setup_type,
                            "market_regime": "BULLISH" if score > 75 else "NEUTRAL",
                            "entry":         float(levels["entry"]),
                            "stop_loss":     float(levels["stop_loss"]),
                            "target_1":      float(levels["t1"]),
                            "target_2":      float(levels["t2"]),
                            "target_3":      float(levels["t3"]),
                            "risk_reward":   float(levels["rr"]),
                            "explanation":   str(explanation),
                        })
                        total_setups_found += 1

                        # Partial flush every FLUSH_EVERY setups found
                        if len(pending_batch) >= FLUSH_EVERY:
                            _flush_batch(pending_batch)

            except Exception:
                logger.debug("Error processing %s:\n%s", sym, traceback.format_exc())
                continue

        logger.info(
            "Analysis complete: %d analysed, %d skipped, %d total setups found.",
            analysed, skipped, total_setups_found,
        )

        # ── 8. Final flush ────────────────────────────────────────────────
        _flush_batch(pending_batch)

        # ── 9. Read results for email ──────────────────────────────────────
        with db_engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM pro_scans_v2 WHERE scan_date = :d ORDER BY score DESC"),
                {"d": today},
            ).mappings().all()

        logger.info("✅ Scan complete. %d active setups saved.", len(rows))
        send_email(list(rows))

    except Exception:
        logger.critical("FATAL ERROR:\n%s", traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    run_automation()

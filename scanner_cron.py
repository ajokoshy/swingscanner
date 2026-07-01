"""
scanner_cron.py  —  SwingScanner v2
Automated daily scan runner (GitHub Actions / any cron).
"""

import logging
import os
import smtplib
import sys
import traceback
from datetime import datetime, timezone, timedelta, date as date_type
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
from sqlalchemy import text

from data_fetcher import DataPipeline, refresh_bhavcopy_cache
from database_manager import init_db, run_migrations, engine as db_engine
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
FLUSH_EVERY     = 25
IST_OFFSET_HRS  = 5.5          # UTC + 5:30

# ---------------------------------------------------------------------------
# Sector Mapping Helpers (Upgrade 2)
# ---------------------------------------------------------------------------

SECTOR_MAP = {
    # Banks & Financials
    "HDFCBANK": "^NSEBANK", "ICICIBANK": "^NSEBANK", "SBIN": "^NSEBANK", 
    "KOTAKBANK": "^NSEBANK", "AXISBANK": "^NSEBANK", "BAJFINANCE": "^NSEBANK",
    "BAJAJFINSV": "^NSEBANK", "PFC": "^NSEBANK", "RECLTD": "^NSEBANK",
    # IT
    "TCS": "^CNXIT", "INFY": "^CNXIT", "WIPRO": "^CNXIT", "HCLTECH": "^CNXIT",
    "TECHM": "^CNXIT", "LTIM": "^CNXIT", "COFORGE": "^CNXIT", "PERSISTENT": "^CNXIT",
    # Auto
    "TATAMOTORS": "^CNXAUTO", "M&M": "^CNXAUTO", "MARUTI": "^CNXAUTO", 
    "HEROMOTOCO": "^CNXAUTO", "BAJAJ-AUTO": "^CNXAUTO", "EICHERMOT": "^CNXAUTO",
    # FMCG
    "HINDUNILVR": "^CNXFMCG", "ITC": "^CNXFMCG", "NESTLEIND": "^CNXFMCG", 
    "BRITANNIA": "^CNXFMCG", "DABUR": "^CNXFMCG", "GODREJCP": "^CNXFMCG",
    # Metal
    "TATASTEEL": "^CNXMETAL", "JSWSTEEL": "^CNXMETAL", "HINDALCO": "^CNXMETAL", 
    "VEDL": "^CNXMETAL", "COALINDIA": "^CNXMETAL", "NATIONALUM": "^CNXMETAL",
    # Pharma
    "SUNPHARMA": "^CNXPHARMA", "CIPLA": "^CNXPHARMA", "DRREDDY": "^CNXPHARMA", 
    "DIVISLAB": "^CNXPHARMA", "TORNTPHARM": "^CNXPHARMA", "APOLLOHOSP": "^CNXPHARMA",
    # Realty
    "DLF": "^CNXREALTY", "GODREJPROP": "^CNXREALTY", "OBEROIRLTY": "^CNXREALTY", 
    "PRESTIGE": "^CNXREALTY", "PHOENIXLTD": "^CNXREALTY"
}

def get_sector_index(symbol: str) -> str | None:
    """Returns matching sector index or None if no specific sector is mapped"""
    return SECTOR_MAP.get(symbol)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

INSERT_SQL = text("""
    INSERT INTO pro_scans_v2
        (symbol, scan_date, score, setup_type, market_regime,
         entry, stop_loss, target_1, target_2, target_3, risk_reward,
         explanation, entry_score, entry_label)
    VALUES
        (:symbol, :scan_date, :score, :setup_type, :market_regime,
         :entry, :stop_loss, :target_1, :target_2, :target_3, :risk_reward,
         :explanation, :entry_score, :entry_label)
    ON CONFLICT ON CONSTRAINT _symbol_date_uc DO NOTHING
""")


def _flush_batch(batch: list[dict]) -> None:
    if not batch:
        return
    with db_engine.connect() as conn:
        conn.execute(INSERT_SQL, batch)
        conn.commit()
    logger.info("Flushed %d setups to DB.", len(batch))
    batch.clear()


def _synthetic_index() -> pd.DataFrame:
    """
    Fallback when Yahoo blocks index fetches.
    pd.bdate_range from a fixed start guarantees exactly 300 rows
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


def send_email(setups: list, scan_date: date_type) -> None:
    sender_email    = os.getenv("EMAIL_USER")
    sender_password = os.getenv("EMAIL_PASS")
    receiver_email  = os.getenv("RECEIVER_EMAIL")

    if not (sender_email and sender_password and receiver_email):
        logger.warning("Email credentials not set — skipping email.")
        return
    if not setups:
        logger.info("No setups found today — email skipped.")
        return

    by_score     = sorted(setups, key=lambda x: x["score"], reverse=True)
    entry_ready  = [s for s in by_score if (s.get("entry_score") or 0) == 5]
    almost_ready = [s for s in by_score if (s.get("entry_score") or 0) == 4]
    elite_count  = sum(1 for s in by_score if s["score"] >= 85)
    strong_count = sum(1 for s in by_score if 75 <= s["score"] < 85)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = (
        f"NSE Swings {scan_date} — "
        f"{len(entry_ready)} entry-ready · {len(by_score)} total"
    )
    msg["From"] = f"NSE Pro Scanner <{sender_email}>"
    msg["To"]   = receiver_email

    # ── style constants ────────────────────────────────────────────────────
    CELL  = "font-family:Arial,sans-serif;font-size:13px;padding:8px 10px;border:1px solid #d0d0d0;"
    CELL_C = CELL + "text-align:center;"
    CELL_R = CELL + "color:#c0392b;"
    CELL_G = CELL + "color:#27ae60;"
    HEAD  = CELL + "font-weight:700;color:#ffffff;"
    HEAD_C = HEAD + "text-align:center;"

    # ── row builders ──
    def _rows_er(rows: list) -> str:
        out = []
        for i, s in enumerate(rows):
            bg = "#f2faf2" if i % 2 == 0 else "#e6f4e6"
            out.append(
                f'<tr>'
                f'<td style="{CELL}background:{bg};"><strong>{s["symbol"]}</strong></td>'
                f'<td style="{CELL_C}background:{bg};">{s["score"]}</td>'
                f'<td style="{CELL}background:{bg};">{s["setup_type"]}</td>'
                f'<td style="{CELL}background:{bg};">&#8377;{s["entry"]}</td>'
                f'<td style="{CELL_R}background:{bg};">&#8377;{s["stop_loss"]}</td>'
                f'<td style="{CELL_G}background:{bg};">&#8377;{s["target_1"]}</td>'
                f'<td style="{CELL_G}background:{bg};">&#8377;{s["target_2"]}</td>'
                f'<td style="{CELL_C}background:{bg};">{s["risk_reward"]}x</td>'
                f'</tr>'
            )
        return "".join(out)

    def _rows_ar(rows: list) -> str:
        out = []
        for i, s in enumerate(rows):
            bg = "#fffef0" if i % 2 == 0 else "#fff8d6"
            out.append(
                f'<tr>'
                f'<td style="{CELL}background:{bg};"><strong>{s["symbol"]}</strong></td>'
                f'<td style="{CELL_C}background:{bg};">{s["score"]}</td>'
                f'<td style="{CELL}background:{bg};">{s["setup_type"]}</td>'
                f'<td style="{CELL}background:{bg};">&#8377;{s["entry"]}</td>'
                f'<td style="{CELL_R}background:{bg};">&#8377;{s["stop_loss"]}</td>'
                f'<td style="{CELL_G}background:{bg};">&#8377;{s["target_1"]}</td>'
                f'<td style="{CELL_C}background:{bg};">{s["risk_reward"]}x</td>'
                f'</tr>'
            )
        return "".join(out)

    def _rows_all(rows: list) -> str:
        out = []
        for i, s in enumerate(rows):
            escore = s.get("entry_score") or 0
            if escore == 5:
                bg = "#f2faf2"
            elif escore == 4:
                bg = "#fffef0"
            else:
                bg = "#ffffff" if i % 2 == 0 else "#f7f7f7"
            badge = "&#128293; " if s["score"] >= 85 else ("&#11088; " if s["score"] >= 75 else "")
            eq    = "&#9989;" if escore == 5 else (f"&#9888;&#65039; {escore}/5" if escore >= 4 else f"{escore}/5")
            out.append(
                f'<tr>'
                f'<td style="{CELL}background:{bg};">{badge}{s["symbol"]}</td>'
                f'<td style="{CELL_C}background:{bg};">{s["score"]}</td>'
                f'<td style="{CELL}background:{bg};">{s["setup_type"]}</td>'
                f'<td style="{CELL_C}background:{bg};">{eq}</td>'
                f'<td style="{CELL}background:{bg};">&#8377;{s["entry"]}</td>'
                f'<td style="{CELL_R}background:{bg};">&#8377;{s["stop_loss"]}</td>'
                f'<td style="{CELL_G}background:{bg};">&#8377;{s["target_1"]}</td>'
                f'<td style="{CELL_C}background:{bg};">{s["risk_reward"]}x</td>'
                f'</tr>'
            )
        return "".join(out)

    def _table(header_row: str, body_rows: str) -> str:
        return (
            '<table width="100%" cellpadding="0" cellspacing="0" '
            'style="border-collapse:collapse;table-layout:auto;">'
            f'{header_row}{body_rows}'
            '</table>'
        )

    def _section(title: str, subtitle: str, header_color: str,
                 bg_color: str, border_color: str, table_html: str) -> str:
        return (
            f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:16px 0;">'
            f'<tr><td style="background:{bg_color};border:2px solid {border_color};'
            f'border-radius:6px;padding:0;overflow:hidden;">'
            f'<table width="100%" cellpadding="0" cellspacing="0">'
            f'<tr><td style="background:{border_color};padding:12px 14px;">'
            f'<p style="margin:0;font-size:14px;font-weight:700;color:#ffffff;">{title}</p>'
            f'<p style="margin:4px 0 0;font-size:11px;color:rgba(255,255,255,0.85);">{subtitle}</p>'
            f'</td></tr>'
            f'<tr><td style="padding:12px 14px;">{table_html}</td></tr>'
            f'</table>'
            f'</td></tr></table>'
        )

    er_section = ""
    if entry_ready:
        hdr = (
            f'<tr style="background:#1a7a3a;">'
            f'<th style="{HEAD}">Symbol</th>'
            f'<th style="{HEAD_C}">Score</th>'
            f'<th style="{HEAD}">Setup</th>'
            f'<th style="{HEAD}">Entry</th>'
            f'<th style="{HEAD}">Stop Loss</th>'
            f'<th style="{HEAD}">T1</th>'
            f'<th style="{HEAD}">T2</th>'
            f'<th style="{HEAD_C}">RR</th>'
            f'</tr>'
        )
        er_section = _section(
            title=f"&#9989; Entry-Ready Now &mdash; {len(entry_ready)} stock{'s' if len(entry_ready) > 1 else ''} (Buy Tomorrow)",
            subtitle="All 5 conditions passed: not extended &middot; RSI in buy zone &middot; volatility contracting &middot; near support &middot; R/R &ge; 2",
            header_color="#1a7a3a",
            bg_color="#f2faf2",
            border_color="#28a745",
            table_html=_table(hdr, _rows_er(entry_ready)),
        )

    ar_section = ""
    if almost_ready:
        hdr = (
            f'<tr style="background:#c68b00;">'
            f'<th style="{HEAD}">Symbol</th>'
            f'<th style="{HEAD_C}">Score</th>'
            f'<th style="{HEAD}">Setup</th>'
            f'<th style="{HEAD}">Entry</th>'
            f'<th style="{HEAD}">Stop Loss</th>'
            f'<th style="{HEAD}">T1</th>'
            f'<th style="{HEAD_C}">RR</th>'
            f'</tr>'
        )
        ar_section = _section(
            title=f"&#9888;&#65039; Almost Ready &mdash; {len(almost_ready)} stock{'s' if len(almost_ready) > 1 else ''} (4/5 conditions)",
            subtitle="One condition failing &mdash; could flip to entry-ready tomorrow. Keep on watchlist.",
            header_color="#c68b00",
            bg_color="#fffef0",
            border_color="#e6a000",
            table_html=_table(hdr, _rows_ar(almost_ready)),
        )

    all_hdr = (
        f'<tr style="background:#003a7a;">'
        f'<th style="{HEAD}">Symbol</th>'
        f'<th style="{HEAD_C}">Score</th>'
        f'<th style="{HEAD}">Setup</th>'
        f'<th style="{HEAD_C}">Entry Quality</th>'
        f'<th style="{HEAD}">Entry</th>'
        f'<th style="{HEAD}">Stop Loss</th>'
        f'<th style="{HEAD}">T1</th>'
        f'<th style="{HEAD_C}">RR</th>'
        f'</tr>'
    )
    all_section = (
        '<p style="font-family:Arial,sans-serif;margin:20px 0 8px;font-size:13px;'
        'font-weight:700;color:#333;">&#128203; All Setups Today</p>' +
        _table(all_hdr, _rows_all(by_score))
    )

    # ── assemble full email ──
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:16px;background:#f4f4f4;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center">
<table width="700" cellpadding="0" cellspacing="0"
  style="max-width:700px;background:#ffffff;border-radius:8px;
         overflow:hidden;font-family:Arial,sans-serif;color:#222;">

  <!-- HEADER -->
  <tr>
    <td style="background:#004a99;padding:18px 20px;border-radius:8px 8px 0 0;">
      <p style="margin:0 0 6px;font-size:20px;font-weight:700;color:#ffffff;">
        &#128737;&#65039; NSE Institutional Swing Setups
      </p>
      <p style="margin:0;font-size:13px;color:rgba(255,255,255,0.9);">
        {scan_date} &nbsp;&middot;&nbsp; {len(by_score)} total &nbsp;&middot;&nbsp;
        <strong>{len(entry_ready)} entry-ready &#9989;</strong>
        &nbsp;&middot;&nbsp; {len(almost_ready)} almost-ready &#9888;&#65039;
        &nbsp;&middot;&nbsp; {elite_count} elite &#128293;
        &nbsp;&middot;&nbsp; {strong_count} strong &#11088;
      </p>
    </td>
  </tr>

  <!-- DISCLAIMER -->
  <tr>
    <td style="background:#fff8e1;border-left:4px solid #f0b400;
               padding:10px 16px;font-size:12px;color:#7a5c00;">
      &#9888;&#65039; <strong>Signals valid for {scan_date} only.</strong>
      Market conditions change daily. Always verify the chart before acting.
      Not investment advice.
    </td>
  </tr>

  <!-- BODY -->
  <tr>
    <td style="padding:16px 20px;">
      {er_section}
      {ar_section}
      {all_section}
      <p style="font-size:11px;color:#aaa;margin:20px 0 0;">
        Open SwingScanner dashboard for full score breakdown and all 3 targets.
      </p>
    </td>
  </tr>

</table>
</td></tr></table>
</body></html>"""

    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        logger.info("✅ Email sent to %s.", receiver_email)
    except Exception as exc:
        logger.error("❌ Email failed: %s", exc)


# ---------------------------------------------------------------------------
# Main scan routine
# ---------------------------------------------------------------------------

def run_automation() -> None:
    try:
        # Use IST date — cron runs at 14:34 UTC = 20:04 IST, same calendar day
        ist_now = datetime.now(timezone.utc) + timedelta(hours=IST_OFFSET_HRS)
        today   = ist_now.date()

        # ── 0. Guard: skip weekends ───────────────────────────────────────
        if today.weekday() >= 5:
            logger.info("Today is %s IST — NSE closed. Exiting.", today.strftime("%A"))
            return

        logger.info("Starting NSE scan for %s (IST)...", today)

        # ── 1. Init DB + run migrations ──────────────────────────────────
        init_db()
        run_migrations()

        # ── 2. Refresh Bhavcopy cache (non-fatal) ─────────────────────────
        try:
            logger.info("Refreshing Bhavcopy cache...")
            refresh_bhavcopy_cache(days=500)
        except Exception as exc:
            logger.warning("Bhavcopy cache refresh failed (non-fatal): %s", exc)

        # ── 3. Purge today's rows so re-runs are idempotent ───────────────
        logger.info("Purging any existing rows for %s...", today)
        with db_engine.connect() as conn:
            conn.execute(text("DELETE FROM pro_scans_v2 WHERE scan_date = :d"), {"d": today})
            conn.commit()

        # ── 4. Fetch symbols ──────────────────────────────────────────────
        symbols = DataPipeline.get_nse500_symbols()
        symbols = [s.strip() for s in symbols if s and not s.startswith("DUMMY")]
        logger.info("Scanning %d symbols...", len(symbols))

        # ── 5. Fetch index data ───────────────────────────────────────────
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

        # Upgrade 2: Pre-fetch standard sectoral indices
        logger.info("Pre-fetching Sectoral Indices...")
        sector_indices = ["^NSEBANK", "^CNXIT", "^CNXAUTO", "^CNXFMCG", "^CNXMETAL", "^CNXPHARMA", "^CNXREALTY"]
        sector_data_cache = {}
        for index_sym in sector_indices:
            try:
                sec_df = DataPipeline.fetch_market_data(index_sym)
                if sec_df is not None and not sec_df.empty:
                    sector_data_cache[index_sym] = sec_df
            except Exception as e:
                logger.warning("Could not pre-fetch sector index %s: %s", index_sym, e)

        # ── 6. Batch fetch stock data ─────────────────────────────────────
        logger.info("Starting batch data fetch...")
        all_data = DataPipeline.fetch_batch_data(symbols)

        if all_data is None or all_data.empty:
            raise RuntimeError(
                "All data sources (yfinance, yahooquery, Bhavcopy) exhausted."
            )

        available_tickers = set(all_data.columns.get_level_values(0))
        logger.info("Data available for %d tickers.", len(available_tickers))

        # ── 7. Analysis loop with partial flush ───────────────────────────
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
                if len(df) < 250:
                    skipped += 1
                    continue

                # Upgrade 2: Retrieve the corresponding sectoral dataframe if mapped
                sector_idx_symbol = get_sector_index(sym)
                sector_df = sector_data_cache.get(sector_idx_symbol) if sector_idx_symbol else None

                # Pass sectoral context to the engine
                engine = InstitutionalEngine(df, mkt_df, mid_df, sector_df=sector_df)
                score, setup_type, explanation = engine.get_contextual_score()
                analysed += 1

                if score >= SCORE_THRESHOLD:
                    levels = RiskManager.get_levels(df)
                    if levels:
                        eq     = engine.get_entry_quality()
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
                            "entry_score":   int(eq["entry_score"]),
                            "entry_label":   str(eq["entry_label"]),
                        })
                        total_setups_found += 1

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

        # ── 9. Read back from DB and email — today's rows only ────────────
        with db_engine.connect() as conn:
            rows = list(conn.execute(
                text("SELECT * FROM pro_scans_v2 WHERE scan_date = :d ORDER BY score DESC"),
                {"d": today},
            ).mappings().all())

        logger.info("✅ Scan complete for %s. %d setups saved.", today, len(rows))
        send_email(rows, today)

    except Exception:
        logger.critical("FATAL ERROR:\n%s", traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    run_automation()

"""
data_fetcher.py  —  SwingScanner v2
Multi-source data pipeline with automatic fallback:
  1. yfinance  +  curl_cffi TLS fingerprint spoofing  (primary)
  2. yahooquery  (different Yahoo endpoint, often works when yfinance is blocked)
  3. NSE Bhavcopy daily cache  (fully Yahoo-independent, built up over time)

Retry logic: exponential back-off per chunk (10 / 20 / 40 s).
Timeout raised to 60 s.  Chunk size kept at 5 (safe on all cloud IPs).
"""

import io
import os
import re
import time
import random
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf
from curl_cffi import requests as crequests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BHAVCOPY_CACHE_DIR = Path(os.getenv("BHAVCOPY_CACHE_DIR", "/tmp/bhavcopy_cache"))
BHAVCOPY_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

# curl_cffi impersonate targets — TLS fingerprint varies per browser build
_IMPERSONATE_TARGETS = ["chrome110", "chrome107", "chrome104", "edge99"]


# ---------------------------------------------------------------------------
# Session factories
# ---------------------------------------------------------------------------

def _new_cffi_session() -> crequests.Session:
    """Create a curl_cffi session that mimics a real browser TLS handshake."""
    target = random.choice(_IMPERSONATE_TARGETS)
    session = crequests.Session(impersonate=target)
    return session


def _new_plain_session() -> requests.Session:
    """Plain requests session with a random UA — used for NSE downloads."""
    s = requests.Session()
    s.headers.update({"User-Agent": random.choice(_USER_AGENTS)})
    return s


# ---------------------------------------------------------------------------
# Symbol list
# ---------------------------------------------------------------------------

def get_nse500_symbols() -> list[str]:
    """
    Fetch the Nifty 500 constituent list from NSE archives.
    Falls back to a hard-coded mini-list on failure.
    """
    url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    for attempt in range(3):
        try:
            resp = _new_plain_session().get(url, timeout=20)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))
            symbols = df["Symbol"].str.strip().unique().tolist()
            clean = [
                s for s in symbols
                if re.match(r"^[A-Z0-9&-]+$", s) and not s.startswith("DUMMY")
            ]
            if clean:
                logger.info("Fetched %d Nifty 500 symbols from NSE.", len(clean))
                return clean
        except Exception as exc:
            logger.warning("Symbol fetch attempt %d failed: %s", attempt + 1, exc)
            time.sleep(5 * (attempt + 1))

    logger.error("Symbol fetch failed after 3 attempts. Using fallback list.")
    return ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
            "HINDUNILVR", "ITC", "KOTAKBANK", "LT", "AXISBANK"]


# ---------------------------------------------------------------------------
# Source 1: yfinance  +  curl_cffi TLS spoofing
# ---------------------------------------------------------------------------

def _prime_cffi_session(session: crequests.Session) -> None:
    """
    Visit Yahoo Finance with the cffi session to obtain cookies/crumb.
    Failures are non-fatal.
    """
    for url in ["https://fc.yahoo.com", "https://finance.yahoo.com"]:
        try:
            session.get(url, timeout=10)
        except Exception:
            pass


def _fetch_via_yfinance(symbol_ns: str,
                        period: str = "2y",
                        session: crequests.Session | None = None) -> pd.DataFrame | None:
    """Single-symbol fetch using yfinance with an optional curl_cffi session."""
    try:
        ticker = yf.Ticker(symbol_ns, session=session)
        df = ticker.history(period=period, interval="1d", auto_adjust=True, timeout=60)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df.dropna(subset=["Close"])
    except Exception as exc:
        logger.debug("yfinance failed for %s: %s", symbol_ns, exc)
        return None


def _fetch_batch_via_yfinance(ns_symbols: list[str],
                               session: crequests.Session) -> pd.DataFrame | None:
    """
    Batch download with:
    - chunks of 5 (safe on cloud IPs)
    - 2–5 s random delay between chunks
    - 3-attempt exponential back-off per chunk

    Single-symbol chunk fix: yf.download() with exactly 1 symbol returns a flat
    DataFrame (no MultiIndex).  We always wrap in pd.concat({sym: df}) to force
    a consistent MultiIndex structure before appending to all_dfs.
    """
    chunks = [ns_symbols[i:i + 5] for i in range(0, len(ns_symbols), 5)]
    all_dfs: list[pd.DataFrame] = []
    total = len(chunks)

    for i, chunk in enumerate(chunks):
        data = None
        for attempt in range(3):
            try:
                time.sleep(random.uniform(2.1, 4.8))
                data = yf.download(
                    chunk,
                    period="2y",
                    interval="1d",
                    group_by="ticker",
                    auto_adjust=True,
                    progress=False,
                    threads=False,
                    session=session,
                    timeout=60,
                )
                if data is not None and not data.empty:
                    break
            except Exception as exc:
                wait = 10 * (2 ** attempt)   # 10 / 20 / 40 s
                logger.warning(
                    "yfinance chunk %d attempt %d/%d failed (%s). "
                    "Waiting %ds...", i, attempt + 1, 3, exc, wait
                )
                time.sleep(wait)

        if data is not None and not data.empty:
            # ── Single-symbol fix ─────────────────────────────────────────
            # yf.download() returns a flat DataFrame when chunk has exactly 1
            # symbol. Wrap it so all results share the same MultiIndex shape.
            if len(chunk) == 1 and not isinstance(data.columns, pd.MultiIndex):
                data = pd.concat({chunk[0]: data}, axis=1)
            all_dfs.append(data)

        if i % 10 == 0:
            logger.info("yfinance batch progress: %.1f%%", (i / total) * 100)

    return pd.concat(all_dfs, axis=1) if all_dfs else None


# ---------------------------------------------------------------------------
# Source 2: yahooquery  (different Yahoo API endpoint)
# ---------------------------------------------------------------------------

def _fetch_via_yahooquery(symbol_ns: str, period: str = "2y") -> pd.DataFrame | None:
    """
    Use yahooquery as a fallback.  It hits a different Yahoo endpoint than yfinance
    and is often reachable when yfinance is blocked.

    yahooquery returns columns in lowercase (open, high, low, close, volume).
    str.capitalize() maps them to Open, High, Low, Close, Volume — no adjclose rename needed.
    """
    try:
        from yahooquery import Ticker as YQTicker   # lazy import — optional dep
        yqt = YQTicker(symbol_ns, validate=False)
        hist = yqt.history(period=period, interval="1d")
        if hist is None or isinstance(hist, str) or hist.empty:
            return None
        # yahooquery returns MultiIndex (symbol, date); flatten to date-only index
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.xs(symbol_ns, level=0)
        hist.index = pd.to_datetime(hist.index)
        hist = hist.rename(columns=str.capitalize)          # open→Open, close→Close etc.
        needed = {"Open", "High", "Low", "Close", "Volume"}
        if not needed.issubset(hist.columns):
            return None
        return hist[list(needed)].dropna(subset=["Close"])
    except Exception as exc:
        logger.debug("yahooquery failed for %s: %s", symbol_ns, exc)
        return None


def _fetch_batch_via_yahooquery(ns_symbols: list[str]) -> pd.DataFrame | None:
    """
    Batch fetch all symbols via yahooquery in one call (it handles batching internally).
    Returns a yfinance-compatible MultiIndex DataFrame.
    """
    try:
        from yahooquery import Ticker as YQTicker
        yqt = YQTicker(ns_symbols, validate=False, asynchronous=True)
        hist = yqt.history(period="2y", interval="1d")
        if hist is None or isinstance(hist, str) or hist.empty:
            return None

        # Rebuild as MultiIndex (symbol, OHLCV) to match yfinance output
        frames = {}
        for sym in ns_symbols:
            try:
                s_df = hist.xs(sym, level=0)
                s_df.index = pd.to_datetime(s_df.index)
                s_df = s_df.rename(columns=str.capitalize)
                s_df = s_df.rename(columns={"Adjclose": "Close"})
                needed = ["Open", "High", "Low", "Close", "Volume"]
                if all(c in s_df.columns for c in needed):
                    frames[sym] = s_df[needed]
            except Exception:
                continue

        if not frames:
            return None

        combined = pd.concat(frames, axis=1)   # MultiIndex columns: (symbol, field)
        return combined
    except Exception as exc:
        logger.warning("yahooquery batch fetch failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Bhavcopy cache helpers — parquet preferred, CSV fallback
# ---------------------------------------------------------------------------

def _has_parquet() -> bool:
    """Return True if a parquet engine is available."""
    try:
        import pyarrow          # noqa: F401
        return True
    except ImportError:
        pass
    try:
        import fastparquet       # noqa: F401
        return True
    except ImportError:
        return False


def _cache_write(df: pd.DataFrame, stem: str) -> None:
    """Write a cache file; parquet if available, otherwise CSV."""
    if _has_parquet():
        df.to_parquet(BHAVCOPY_CACHE_DIR / f"{stem}.parquet", index=False)
    else:
        df.to_csv(BHAVCOPY_CACHE_DIR / f"{stem}.csv", index=False)


def _cache_read(stem: str) -> pd.DataFrame | None:
    """Read a cache file; try parquet first, then CSV."""
    for path, reader in [
        (BHAVCOPY_CACHE_DIR / f"{stem}.parquet", pd.read_parquet),
        (BHAVCOPY_CACHE_DIR / f"{stem}.csv",     pd.read_csv),
    ]:
        if path.exists():
            try:
                return reader(path)
            except Exception:
                continue
    return None


def _cache_exists(stem: str) -> bool:
    return (
        (BHAVCOPY_CACHE_DIR / f"{stem}.parquet").exists()
        or (BHAVCOPY_CACHE_DIR / f"{stem}.csv").exists()
    )


# ---------------------------------------------------------------------------
# Source 3: NSE Bhavcopy daily cache
# ---------------------------------------------------------------------------

def _bhavcopy_url(for_date: date) -> str:
    d = for_date.strftime("%d%b%Y").upper()
    return f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"


def _download_bhavcopy(for_date: date) -> pd.DataFrame | None:
    """Download a single day's Bhavcopy and cache it (parquet if available, else CSV)."""
    stem = for_date.isoformat()
    cached = _cache_read(stem)
    if cached is not None:
        return cached

    url = _bhavcopy_url(for_date)
    try:
        resp = _new_plain_session().get(url, timeout=30)
        if resp.status_code != 200:
            return None
        df = pd.read_csv(io.StringIO(resp.text), skipinitialspace=True)
        df.columns = df.columns.str.strip()
        # Keep only EQ series
        series_col = "SERIES" if "SERIES" in df.columns else "Series"
        if series_col in df.columns:
            df = df[df[series_col].str.strip() == "EQ"]
        col_map = {
            "SYMBOL": "Symbol", "OPEN_PRICE": "Open", "HIGH_PRICE": "High",
            "LOW_PRICE": "Low", "CLOSE_PRICE": "Close", "TTL_TRD_QNTY": "Volume",
        }
        df = df.rename(columns=col_map)
        needed = ["Symbol", "Open", "High", "Low", "Close", "Volume"]
        if not all(c in df.columns for c in needed):
            return None
        df = df[needed].copy()
        df["Date"] = pd.Timestamp(for_date)
        _cache_write(df, stem)
        return df
    except Exception as exc:
        logger.debug("Bhavcopy download failed for %s: %s", for_date, exc)
        return None


def refresh_bhavcopy_cache(days: int = 500) -> None:
    """
    Download the last `days` trading days of Bhavcopy files that aren't cached yet.
    Call once daily at scan start so the cache gradually builds a 2-year history.
    """
    today = date.today()
    missing: list[date] = []
    for delta in range(days):
        d = today - timedelta(days=delta)
        if d.weekday() >= 5:                    # skip weekends
            continue
        if not _cache_exists(d.isoformat()):
            missing.append(d)

    if not missing:
        logger.info("Bhavcopy cache is up to date.")
        return

    logger.info("Refreshing Bhavcopy cache: %d missing days...", len(missing))
    for d in sorted(missing):
        _download_bhavcopy(d)
        time.sleep(0.5)   # be polite to NSE archives


def _fetch_from_bhavcopy(symbol: str) -> pd.DataFrame | None:
    """
    Reconstruct a 2-year OHLCV history for one symbol from cached Bhavcopy files.
    Works with both parquet and CSV cache files.
    """
    # Collect all cache stems (date strings)
    stems: set[str] = set()
    for p in BHAVCOPY_CACHE_DIR.glob("*.parquet"):
        stems.add(p.stem)
    for p in BHAVCOPY_CACHE_DIR.glob("*.csv"):
        stems.add(p.stem)

    if not stems:
        return None

    frames: list[pd.DataFrame] = []
    for stem in sorted(stems):
        day = _cache_read(stem)
        if day is None:
            continue
        try:
            row = day[day["Symbol"].str.strip() == symbol]
            if not row.empty:
                frames.append(row)
        except Exception:
            continue

    if not frames:
        return None

    combined = pd.concat(frames, ignore_index=True)
    combined["Date"] = pd.to_datetime(combined["Date"])
    combined = combined.sort_values("Date").set_index("Date")
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        combined[col] = pd.to_numeric(combined[col], errors="coerce")
    return combined.dropna(subset=["Close"])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class DataPipeline:
    """
    Public interface for the rest of the app.
    All methods try sources in priority order and return the first usable result.
    """

    # One shared cffi session per process — keeps cookies alive
    _cffi_session: crequests.Session | None = None

    @classmethod
    def _get_cffi_session(cls) -> crequests.Session:
        if cls._cffi_session is None:
            cls._cffi_session = _new_cffi_session()
            _prime_cffi_session(cls._cffi_session)
        return cls._cffi_session

    @staticmethod
    def get_nse500_symbols() -> list[str]:
        return get_nse500_symbols()

    @classmethod
    def fetch_market_data(cls, symbol: str, period: str = "2y") -> pd.DataFrame | None:
        """
        Fetch a single ticker (index or stock).
        Tries: yfinance+cffi → yahooquery → returns None with synthetic fallback
        handled upstream.
        """
        sym_ns = symbol if symbol.startswith("^") else f"{symbol}.NS"
        session = cls._get_cffi_session()

        # Source 1
        df = _fetch_via_yfinance(sym_ns, period, session)
        if df is not None and len(df) > 20:
            return df

        # Source 2
        df = _fetch_via_yahooquery(sym_ns, period)
        if df is not None and len(df) > 20:
            return df

        # Source 3 (stocks only — not useful for indices)
        if not symbol.startswith("^"):
            df = _fetch_from_bhavcopy(symbol)
            if df is not None and len(df) > 20:
                return df

        return None

    @classmethod
    def fetch_batch_data(cls, symbols: list[str]) -> pd.DataFrame | None:
        """
        Batch fetch for all symbols.
        Tries: yfinance+cffi batch → yahooquery batch → single-pass optimized Bhavcopy read.

        Returns a MultiIndex DataFrame compatible with the existing scanner loop:
            all_data[f"{sym}.NS"]  →  OHLCV DataFrame
        """
        ns_symbols = [f"{s}.NS" for s in symbols]
        session = cls._get_cffi_session()

        # ── Source 1: yfinance batch ──────────────────────────────────────
        logger.info("Batch fetch: trying yfinance+cffi (%d symbols)...", len(ns_symbols))
        data = _fetch_batch_via_yfinance(ns_symbols, session)
        if data is not None and not data.empty:
            coverage = _batch_coverage(data, ns_symbols)
            logger.info("yfinance batch: %.0f%% symbol coverage.", coverage * 100)
            if coverage >= 0.50:     # accept if ≥50% of symbols came through
                return data
            logger.warning("yfinance coverage too low (%.0f%%). Trying yahooquery...",
                           coverage * 100)

        # ── Source 2: yahooquery batch ────────────────────────────────────
        logger.info("Batch fetch: trying yahooquery (%d symbols)...", len(ns_symbols))
        data = _fetch_batch_via_yahooquery(ns_symbols)
        if data is not None and not data.empty:
            coverage = _batch_coverage(data, ns_symbols)
            logger.info("yahooquery batch: %.0f%% symbol coverage.", coverage * 100)
            if coverage >= 0.30:
                return data

        # ── Source 3: Bhavcopy optimized batch read ───────────────────────
        logger.info("Batch fetch: falling back to Bhavcopy cache (optimized batch read)...")
        stems = sorted({p.stem for p in BHAVCOPY_CACHE_DIR.glob("*.parquet")} |
                       {p.stem for p in BHAVCOPY_CACHE_DIR.glob("*.csv")})

        if not stems:
            logger.error("No Bhavcopy cache files found.")
            return None

        logger.info("Loading %d daily Bhavcopy files into memory...", len(stems))
        daily_dfs = []
        for stem in stems:
            day_df = _cache_read(stem)
            if day_df is not None:
                daily_dfs.append(day_df)

        if not daily_dfs:
            logger.error("Could not load any daily Bhavcopy files from cache.")
            return None

        master_df = pd.concat(daily_dfs, ignore_index=True)
        master_df["Date"] = pd.to_datetime(master_df["Date"])
        master_df["Symbol"] = master_df["Symbol"].str.strip()

        # Group and map to the target multi-index format
        frames: dict[str, pd.DataFrame] = {}
        clean_symbols = [s.strip() for s in symbols]
        
        for sym in clean_symbols:
            sym_data = master_df[master_df["Symbol"] == sym]
            if not sym_data.empty:
                sym_data = sym_data.sort_values("Date").set_index("Date")
                for col in ["Open", "High", "Low", "Close", "Volume"]:
                    sym_data[col] = pd.to_numeric(sym_data[col], errors="coerce")
                
                clean_df = sym_data[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                if len(clean_df) > 20:
                    frames[f"{sym}.NS"] = clean_df

        if frames:
            logger.info("Bhavcopy: recovered %d/%d symbols.", len(frames), len(symbols))
            return pd.concat(frames, axis=1)

        logger.error("All data sources exhausted. Cannot fetch batch data.")
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _batch_coverage(data: pd.DataFrame, ns_symbols: list[str]) -> float:
    """Fraction of requested symbols present in the batch result."""
    if data is None or data.empty:
        return 0.0
    try:
        present = set(data.columns.get_level_values(0))
        return len(present.intersection(ns_symbols)) / len(ns_symbols)
    except Exception:
        return 0.0

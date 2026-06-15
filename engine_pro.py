"""
engine_pro.py  —  SwingScanner v2
Institutional scoring engine.

pandas_ta removed entirely — replaced with inline implementations of the
4 functions we actually use (ema, rsi, atr, sma). All pure pandas/numpy math.
This eliminates the numba → llvmlite chain that breaks on Python 3.14.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inline indicator implementations (replaces pandas_ta dependency)
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, length: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def _sma(series: pd.Series, length: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=length, min_periods=length).mean()


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder smoothing)."""
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta.clip(upper=0))
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Average True Range (Wilder smoothing)."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class InstitutionalEngine:
    def __init__(self, stock_df: pd.DataFrame, market_df: pd.DataFrame, midcap_df: pd.DataFrame):
        self.df  = stock_df.copy()
        self.mkt = market_df.copy()
        self.mid = midcap_df.copy()

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df["ema20"]   = _ema(df["Close"], 20)
        df["ema50"]   = _ema(df["Close"], 50)
        df["ema200"]  = _ema(df["Close"], 200)
        df["rsi"]     = _rsi(df["Close"], 14)
        df["atr"]     = _atr(df["High"], df["Low"], df["Close"], 14)
        df["vol_sma"] = _sma(df["Volume"], 20)

        # Shifted highs — no look-ahead bias
        df["h20"]  = df["High"].rolling(window=20).max().shift(1)
        df["h50"]  = df["High"].rolling(window=50).max().shift(1)
        df["h252"] = df["High"].rolling(window=252).max().shift(1)

        return df.dropna(subset=["ema200", "rsi", "atr"])

    def get_contextual_score(self) -> tuple[int, str, str]:
        """
        Score a stock setup 0–100 across 6 components:
          Trend (30) · Momentum (20) · Volume (20) · Breakout/Setup (20)
          Market Regime (5) · Relative Strength (5)

        Returns (score, setup_type, explanation_string)
        """
        self.df  = self._calculate_indicators(self.df)
        self.mkt = self._calculate_indicators(self.mkt)

        if len(self.df) < 5 or len(self.mkt) < 5:
            return 0, "Insufficient Data", "Stock history too short for analysis"

        last     = self.df.iloc[-1]
        mkt_last = self.mkt.iloc[-1]

        scores       = {"Trend": 0, "Momentum": 0, "Volume": 0, "Breakout": 0, "Market": 0, "RS": 0}
        explanations = []

        # ── 1. Trend (30 pts) ─────────────────────────────────────────────
        if last["Close"] > last["ema200"]:
            scores["Trend"] += 15
        if last["ema20"] > last["ema50"] > last["ema200"]:
            scores["Trend"] += 15
        explanations.append(f"Trend: {scores['Trend']}/30")

        # ── 2. Momentum (20 pts) ──────────────────────────────────────────
        rsi = last["rsi"]
        if 55 <= rsi <= 70:
            scores["Momentum"] = 20
        elif 45 <= rsi < 55:
            scores["Momentum"] = 10
        explanations.append(f"Momentum (RSI {rsi:.0f}): {scores['Momentum']}/20")

        # ── 3. Volume (20 pts) ────────────────────────────────────────────
        if last["Volume"] > last["vol_sma"] * 1.5:
            scores["Volume"] = 20
            explanations.append("Institutional vol spike (1.5× avg)")
        elif last["Volume"] > last["vol_sma"]:
            scores["Volume"] = 10
            explanations.append("Above-avg volume")
        else:
            explanations.append("Volume: below avg")

        # ── 4. Breakout / Setup detection (20 pts) ────────────────────────
        setup_type = "Base Formation"

        if len(self.df) >= 252 and last["Close"] > last["h252"]:
            scores["Breakout"] = 20
            setup_type = "52-Week High Breakout"
        elif last["Close"] > last["h50"]:
            scores["Breakout"] = 15
            setup_type = "50-Day High Breakout"
        elif last["Close"] > last["h20"]:
            scores["Breakout"] = 10
            setup_type = "20-Day High Breakout"

        if scores["Breakout"] == 0:
            lookback     = min(10, len(self.df))
            atr_avg      = self.df["atr"].iloc[-lookback:-1].mean()
            price_spread = (
                self.df["High"].iloc[-lookback:].max()
                / self.df["Low"].iloc[-lookback:].min()
            ) - 1

            if (
                last["atr"] < atr_avg * 0.9
                and last["Volume"] < last["vol_sma"]
                and price_spread < 0.08
            ):
                scores["Breakout"] = 18
                setup_type = "VCP Pattern"
                explanations.append("VCP: vol+price contraction detected")
            elif 0.98 <= (last["Close"] / last["ema50"]) <= 1.02:
                scores["Breakout"] = 15
                setup_type = "Pullback to EMA50"
                explanations.append("Healthy pullback to EMA50")

        explanations.append(f"Setup ({setup_type}): {scores['Breakout']}/20")

        # ── 5. Market regime (5 pts) ──────────────────────────────────────
        if mkt_last["Close"] > mkt_last["ema200"]:
            scores["Market"] += 3
        if mkt_last["rsi"] > 50:
            scores["Market"] += 2
        explanations.append(f"Market regime: {scores['Market']}/5")

        # ── 6. Relative strength (5 pts) ──────────────────────────────────
        lookback_rs = min(63, len(self.df), len(self.mkt))
        if lookback_rs > 5:
            stock_ret = (self.df["Close"].iloc[-1] / self.df["Close"].iloc[-lookback_rs]) - 1
            mkt_ret   = (self.mkt["Close"].iloc[-1] / self.mkt["Close"].iloc[-lookback_rs]) - 1
            if stock_ret > mkt_ret:
                scores["RS"] = 5
                explanations.append("RS: outperforming Nifty (63d)")
            else:
                scores["RS"] = 2
                explanations.append("RS: lagging Nifty (63d)")

        total = sum(scores.values())
        return int(total), setup_type, " | ".join(explanations)

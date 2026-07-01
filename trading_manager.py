"""
trading_manager.py  —  SwingScanner v2
ATR-based risk levels.

pandas_ta removed — _ema and _atr implemented inline using pure pandas,
identical math to the functions in engine_pro.py.
"""

import pandas as pd


# ---------------------------------------------------------------------------
# Inline indicator helpers (same logic as engine_pro.py)
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


# ---------------------------------------------------------------------------
# Risk Manager
# ---------------------------------------------------------------------------

class RiskManager:
    @staticmethod
    def get_levels(df: pd.DataFrame) -> dict | None:
        """
        Calculate ATR-based entry, stop-loss, and targets.
        Returns None if data is insufficient or R/R < 2.
        """
        df = df.copy()

        df["ema50"] = _ema(df["Close"], 50)
        df["atr"]   = _atr(df["High"], df["Low"], df["Close"], 14)

        if len(df) < 14 or df["atr"].isna().all():
            return None

        last  = df.iloc[-1]
        price = float(last["Close"])
        atr   = float(last["atr"])

        # Prevent processing for zero-volatility or penny stocks under 1 Rupee
        if atr <= 0.01 or pd.isna(atr) or price <= 1.0:
            return None

        stop_loss = price - (2.0 * atr)
        risk      = price - stop_loss

        # Ensure stop loss is mathematically logical and positive
        if risk <= 0.01 or stop_loss <= 0:
            return None

        t1 = price + (risk * 2.0)
        t2 = price + (risk * 3.0)
        t3 = price + (risk * 5.0)
        rr = (t1 - price) / risk

        if rr < 1.9:   # floating-point tolerance
            return None

        return {
            "entry":     round(price,     2),
            "stop_loss": round(stop_loss, 2),
            "t1":        round(t1,        2),
            "t2":        round(t2,        2),
            "t3":        round(t3,        2),
            "rr":        round(rr,        2),
        }

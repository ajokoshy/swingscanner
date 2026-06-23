"""
engine_pro.py  —  SwingScanner v2
Institutional scoring engine + Entry Quality filter.

pandas_ta removed — all indicators implemented inline with pure pandas/numpy.

Two outputs per stock:
  1. get_contextual_score()  — 0-100 trend/momentum/volume/breakout score (unchanged)
  2. get_entry_quality()     — strict 5-condition entry filter for "buyable tomorrow"
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inline indicator implementations
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def _sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length, min_periods=length).mean()


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta.clip(upper=0))
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
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
        self._indicators_calculated = False

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df["ema20"]   = _ema(df["Close"], 20)
        df["ema50"]   = _ema(df["Close"], 50)
        df["ema200"]  = _ema(df["Close"], 200)
        df["rsi"]     = _rsi(df["Close"], 14)
        df["atr"]     = _atr(df["High"], df["Low"], df["Close"], 14)
        df["vol_sma"] = _sma(df["Volume"], 20)
        df["h20"]     = df["High"].rolling(window=20).max().shift(1)
        df["h50"]     = df["High"].rolling(window=50).max().shift(1)
        df["h252"]    = df["High"].rolling(window=252).max().shift(1)
        return df.dropna(subset=["ema200", "rsi", "atr"])

    def _ensure_indicators(self) -> None:
        if not self._indicators_calculated:
            self.df  = self._calculate_indicators(self.df)
            self.mkt = self._calculate_indicators(self.mkt)
            self._indicators_calculated = True

    # ------------------------------------------------------------------ #
    #  Score (unchanged)                                                   #
    # ------------------------------------------------------------------ #

    def get_contextual_score(self) -> tuple[int, str, str]:
        """
        Score 0-100 across 6 components:
          Trend (30) · Momentum (20) · Volume (20) · Breakout/Setup (20)
          Market Regime (5) · Relative Strength (5)
        """
        self._ensure_indicators()

        if len(self.df) < 5 or len(self.mkt) < 5:
            return 0, "Insufficient Data", "Stock history too short for analysis"

        last     = self.df.iloc[-1]
        mkt_last = self.mkt.iloc[-1]

        scores       = {"Trend": 0, "Momentum": 0, "Volume": 0, "Breakout": 0, "Market": 0, "RS": 0}
        explanations = []

        # 1. Trend
        if last["Close"] > last["ema200"]:
            scores["Trend"] += 15
        if last["ema20"] > last["ema50"] > last["ema200"]:
            scores["Trend"] += 15
        explanations.append(f"Trend: {scores['Trend']}/30")

        # 2. Momentum
        rsi = last["rsi"]
        if 55 <= rsi <= 70:
            scores["Momentum"] = 20
        elif 45 <= rsi < 55:
            scores["Momentum"] = 10
        explanations.append(f"Momentum (RSI {rsi:.0f}): {scores['Momentum']}/20")

        # 3. Volume
        if last["Volume"] > last["vol_sma"] * 1.5:
            scores["Volume"] = 20
            explanations.append("Institutional vol spike (1.5× avg)")
        elif last["Volume"] > last["vol_sma"]:
            scores["Volume"] = 10
            explanations.append("Above-avg volume")
        else:
            explanations.append("Volume: below avg")

        # 4. Breakout / Setup
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

        # 5. Market regime
        if mkt_last["Close"] > mkt_last["ema200"]:
            scores["Market"] += 3
        if mkt_last["rsi"] > 50:
            scores["Market"] += 2
        explanations.append(f"Market regime: {scores['Market']}/5")

        # 6. Relative strength
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

    # ------------------------------------------------------------------ #
    #  Entry Quality Filter — "Is this actually buyable tomorrow?"         #
    # ------------------------------------------------------------------ #

    def get_entry_quality(self) -> dict:
        """
        Checks 5 strict entry conditions. ALL must pass for a stock to be
        considered enterable tomorrow. Returns a dict with:
          - entry_ready: bool  — True only if all 5 conditions pass
          - conditions: dict   — each condition name → (passed: bool, detail: str)
          - entry_label: str   — human-readable verdict
          - entry_score: int   — 0-5 (how many conditions passed)

        The 5 conditions:
          1. NOT EXTENDED  — price ≤ 3% above the nearest key level (EMA20/50 or recent high)
          2. RSI BUYZONE   — RSI between 45 and 68 (not overbought, not weak)
          3. ATR TIGHTENING — today's ATR ≤ 110% of the 10-day avg ATR (volatility contracting)
          4. NEAR SUPPORT  — price within 5% above EMA20 or EMA50 (not in mid-air)
          5. RISK/REWARD   — potential move to 20-day high ≥ 2× the ATR stop distance
        """
        self._ensure_indicators()

        if len(self.df) < 20:
            return {
                "entry_ready": False,
                "conditions":  {},
                "entry_label": "Insufficient data",
                "entry_score": 0,
            }

        last    = self.df.iloc[-1]
        price   = float(last["Close"])
        rsi     = float(last["rsi"])
        atr     = float(last["atr"])
        ema20   = float(last["ema20"])
        ema50   = float(last["ema50"])
        vol_sma = float(last["vol_sma"])

        # 10-day average ATR for tightening comparison
        atr_10_avg = float(self.df["atr"].iloc[-11:-1].mean())

        # Nearest key level below price
        key_level = max(ema20, ema50)

        # 20-day high (potential target)
        high_20 = float(self.df["High"].iloc[-20:].max())

        conditions: dict[str, tuple[bool, str]] = {}

        # ── Condition 1: Not Extended ─────────────────────────────────────
        # Price should be within 3% above the nearest key level.
        # If it's run up 10% already, the easy money is gone.
        extension_pct = ((price - key_level) / key_level) * 100 if key_level > 0 else 999
        c1 = extension_pct <= 3.0
        conditions["Not Extended"] = (
            c1,
            f"Price is {extension_pct:.1f}% above key level "
            f"(EMA20/50 ₹{key_level:.0f}) — limit is 3%"
        )

        # ── Condition 2: RSI Buy Zone ─────────────────────────────────────
        # RSI 45-68: strong enough to be in an uptrend, not so hot it's overbought.
        # Above 68 = extended, risky entry. Below 45 = losing momentum.
        c2 = 45 <= rsi <= 68
        conditions["RSI Buy Zone"] = (
            c2,
            f"RSI is {rsi:.0f} — needs to be 45–68 for safe entry"
        )

        # ── Condition 3: Volatility Tightening ───────────────────────────
        # ATR contracting means the stock is coiling, not thrashing around.
        # Breakouts from tight bases have better success rates.
        if atr_10_avg > 0:
            atr_ratio = atr / atr_10_avg
            c3 = atr_ratio <= 1.10
            conditions["Volatility Tightening"] = (
                c3,
                f"ATR is {atr_ratio:.2f}× the 10-day avg "
                f"(₹{atr:.1f} vs avg ₹{atr_10_avg:.1f}) — limit is 1.10×"
            )
        else:
            c3 = False
            conditions["Volatility Tightening"] = (False, "ATR data unavailable")

        # ── Condition 4: Near Support ─────────────────────────────────────
        # Price within 5% above EMA20 or EMA50 = still near the launchpad.
        # More than 5% above = chasing, stop loss becomes too wide.
        near_ema20 = ((price - ema20) / ema20) * 100 if ema20 > 0 else 999
        near_ema50 = ((price - ema50) / ema50) * 100 if ema50 > 0 else 999
        best_proximity = min(near_ema20, near_ema50)
        c4 = best_proximity <= 5.0
        closer_ema = "EMA20" if near_ema20 < near_ema50 else "EMA50"
        conditions["Near Support"] = (
            c4,
            f"Price is {best_proximity:.1f}% above {closer_ema} — limit is 5%"
        )

        # ── Condition 5: Reward/Risk ≥ 2 ─────────────────────────────────
        # Potential upside (to 20-day high) must be at least 2× the ATR stop.
        # No point entering if the upside is equal to or less than the risk.
        stop_distance  = 2.0 * atr                    # our standard 2-ATR stop
        upside         = high_20 - price
        rr_ratio       = upside / stop_distance if stop_distance > 0 else 0
        c5 = rr_ratio >= 2.0
        conditions["Risk/Reward ≥ 2"] = (
            c5,
            f"Upside to 20d high ₹{high_20:.0f} = ₹{upside:.0f} "
            f"vs 2-ATR stop ₹{stop_distance:.0f} → RR {rr_ratio:.1f}x"
        )

        entry_score = sum(1 for passed, _ in conditions.values() if passed)
        entry_ready = entry_score == 5

        if entry_ready:
            entry_label = "✅ READY TO BUY — all 5 conditions met"
        elif entry_score >= 4:
            entry_label = "⚠️ ALMOST — 1 condition failing, watch closely"
        elif entry_score >= 3:
            entry_label = "🔶 WAIT — needs improvement before entry"
        else:
            entry_label = "❌ NOT YET — too many conditions failing"

        return {
            "entry_ready":  entry_ready,
            "conditions":   conditions,
            "entry_label":  entry_label,
            "entry_score":  entry_score,
        }

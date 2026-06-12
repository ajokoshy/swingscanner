class BacktestEngine:
    @staticmethod
    def run_validation(symbol, entry_price, target, stop, df_after):
        """Measures 20-day forward performance"""
        if df_after.empty: return None
        max_high = df_after['High'].max()
        min_low = df_after['Low'].min()
        
        success = False
        if min_low <= stop: success = False
        elif max_high >= target: success = True
        
        return success

    @staticmethod
    def calculate_metrics(trades):
        """Win rate, Profit Factor, CAGR etc."""
        if not trades: return {}
        wins = [t for t in trades if t['success']]
        win_rate = len(wins) / len(trades)
        # Logic for expectancy and drawdown...
        return {"win_rate": win_rate, "trades": len(trades)}
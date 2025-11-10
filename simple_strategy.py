import pandas as pd


class SimpleMACDStrategy:
    """
    非常简单的 MACD 策略（15m 上直接用 MACD 金叉/死叉）：
    - signal = 1  表示这根 15m K 线出现多头入场信号
    - signal = -1 表示空头入场信号
    - signal = 0  表示无操作
    """

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def _calc_macd(self, close: pd.Series):
        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=self.signal, adjust=False).mean()
        hist = macd - macd_signal
        return macd, macd_signal, hist

    def generate_signals(self, df_15m: pd.DataFrame) -> pd.DataFrame:
        """
        输入:
            df_15m: index 为时间, 列至少包含 close
        返回:
            在 df 基础上增加: macd, macd_signal, macd_hist, signal
        """
        df = df_15m.sort_index().copy()
        macd, macd_sig, macd_hist = self._calc_macd(df["close"])

        df["macd"] = macd
        df["macd_signal"] = macd_sig
        df["macd_hist"] = macd_hist

        # 金叉：从下往上
        long_entry = (df["macd"] > df["macd_signal"]) & (
            df["macd"].shift(1) <= df["macd_signal"].shift(1)
        )

        # 死叉：从上往下
        short_entry = (df["macd"] < df["macd_signal"]) & (
            df["macd"].shift(1) >= df["macd_signal"].shift(1)
        )

        df["simple_entry_long"] = long_entry.astype("int8")
        df["simple_entry_short"] = short_entry.astype("int8")

        df["simple_signal"] = df["simple_entry_long"].astype(int) - df["simple_entry_short"].astype(int)
        return df

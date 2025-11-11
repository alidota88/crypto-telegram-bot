from dataclasses import dataclass

import pandas as pd


@dataclass
class SimpleMACDStrategyConfig:
    """参数配置，便于后续根据市场调整节奏。"""

    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    ema_trend_period: int = 120  # 趋势过滤，默认 ~1 日
    ema_trigger_period: int = 34  # 触发用的较快 EMA

    rsi_period: int = 14
    rsi_long_threshold: float = 55.0
    rsi_short_threshold: float = 45.0

    hist_strength: float = 0.0  # 过滤 MACD 柱子太弱的信号
    hist_lookback: int = 3


class SimpleMACDStrategy:
    """更注重稳健性的 15m MACD 趋势跟随策略。

    - 保留 MACD 金叉/死叉作为入场核心，但增加 EMA + RSI 筛选，降低震荡区间的假信号。
    - `simple_signal` 仍为 {-1, 0, 1}，方便交易引擎继续使用；同时额外输出过滤指标列，便于调参。"""

    def __init__(self, cfg: SimpleMACDStrategyConfig | None = None):
        self.cfg = cfg or SimpleMACDStrategyConfig()

    def _calc_macd(self, close: pd.Series):
        ema_fast = close.ewm(span=self.cfg.macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.cfg.macd_slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=self.cfg.macd_signal, adjust=False).mean()
        hist = macd - macd_signal
        return macd, macd_signal, hist

    def _calc_rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.rolling(self.cfg.rsi_period, min_periods=self.cfg.rsi_period).mean()
        avg_loss = loss.rolling(self.cfg.rsi_period, min_periods=self.cfg.rsi_period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def generate_signals(self, df_15m: pd.DataFrame) -> pd.DataFrame:
        """
        输入:
            df_15m: index 为时间, 列至少包含 close
        返回:
            在 df 基础上增加: MACD、EMA、RSI、信号列
        """
        cfg = self.cfg
        df = df_15m.sort_index().copy()

        macd, macd_sig, macd_hist = self._calc_macd(df["close"])

        df["macd"] = macd
        df["macd_signal"] = macd_sig
        df["macd_hist"] = macd_hist

        df["ema_trend"] = df["close"].ewm(span=cfg.ema_trend_period, adjust=False).mean()
        df["ema_trigger"] = df["close"].ewm(span=cfg.ema_trigger_period, adjust=False).mean()
        df["rsi"] = self._calc_rsi(df["close"])

        # 过滤：顺趋势 & RSI 支撑 & MACD 柱动能不弱
        hist_roll = df["macd_hist"].rolling(cfg.hist_lookback, min_periods=1).mean()

        long_trend = df["close"] > df["ema_trend"]
        short_trend = df["close"] < df["ema_trend"]

        long_rsi_ok = df["rsi"] >= cfg.rsi_long_threshold
        short_rsi_ok = df["rsi"] <= cfg.rsi_short_threshold

        long_hist_ok = hist_roll >= cfg.hist_strength
        short_hist_ok = hist_roll <= -cfg.hist_strength if cfg.hist_strength > 0 else hist_roll <= cfg.hist_strength

        # 金叉：从下往上
        macd_cross_up = (df["macd"] > df["macd_signal"]) & (
            df["macd"].shift(1) <= df["macd_signal"].shift(1)
        )

        # 死叉：从上往下
        macd_cross_down = (df["macd"] < df["macd_signal"]) & (
            df["macd"].shift(1) >= df["macd_signal"].shift(1)
        )

        long_entry = macd_cross_up & long_trend & long_rsi_ok & long_hist_ok
        short_entry = macd_cross_down & short_trend & short_rsi_ok & short_hist_ok

        df["simple_entry_long"] = long_entry.astype("int8")
        df["simple_entry_short"] = short_entry.astype("int8")

        # 出场辅助：当价格重新跌破快速 EMA 或动能衰减时提示观望
        exit_long = (
            (df["macd_hist"] < 0)
            | (df["close"] < df["ema_trigger"])
            | (df["rsi"] < 50)
        ).fillna(False)
        exit_short = (
            (df["macd_hist"] > 0)
            | (df["close"] > df["ema_trigger"])
            | (df["rsi"] > 50)
        ).fillna(False)
        df["simple_exit_long"] = exit_long.astype("int8")
        df["simple_exit_short"] = exit_short.astype("int8")

        signal_state = []
        current = 0
        for is_long, is_short, do_exit_long, do_exit_short in zip(
            long_entry, short_entry, exit_long, exit_short
        ):
            if current == 1 and do_exit_long:
                current = 0
            elif current == -1 and do_exit_short:
                current = 0

            if is_long:
                current = 1
            elif is_short:
                current = -1

            signal_state.append(current)

        df["simple_signal"] = pd.Series(signal_state, index=df.index, dtype="int8")

        return df

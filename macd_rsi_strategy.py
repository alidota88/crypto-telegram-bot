from dataclasses import dataclass
import pandas as pd
import numpy as np

@dataclass
class MACDRSIStrategyConfig:
    # MACD/RSI/ATR 参数
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_period: int = 14
    atr_period: int = 14

    # 趋势过滤（4h）
    rsi_trend_high: float = 55.0
    rsi_trend_low: float = 45.0

    # 入场 RSI 阈值（15m）
    rsi_entry_upper: float = 50.0  # 多单：RSI 上穿这个值
    rsi_entry_lower: float = 50.0  # 空单：RSI 下穿这个值

    # 回调确认的窗口（15m）
    lookback_bars: int = 20       # 过去 N 根 K 线内 RSI 必须有过“回调”

    # 止损 ATR 倍数
    atr_sl_mult: float = 2.5      # 默认 2.5 ATR


class MACDRSIStrategy:
    """
    多周期 MACD + RSI 多空策略
    - 4h：趋势过滤
    - 15m：回调后入场
    - 输出信号，不直接做资金管理和持仓回放
    """

    def __init__(self, cfg: MACDRSIStrategyConfig = None):
        self.cfg = cfg or MACDRSIStrategyConfig()

    # ========= 指标工具函数 =========
    def _calc_macd(self, close: pd.Series, fast: int, slow: int, signal: int):
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal, adjust=False).mean()
        hist = macd - macd_signal
        return macd, macd_signal, hist

    def _calc_rsi(self, close: pd.Series, period: int):
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        # 这里用简单滚动平均，够用了；你也可以换成 RMA
        avg_gain = gain.rolling(period, min_periods=period).mean()
        avg_loss = loss.rolling(period, min_periods=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _calc_atr(self, df: pd.DataFrame, period: int):
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period, min_periods=period).mean()
        return atr

    # ========= 4h 趋势过滤 =========
    def _calc_trend_4h(self, df_15m: pd.DataFrame) -> pd.Series:
        """
        输入：15m K 线
        输出：对齐到 15m 的趋势信号（1 多 / -1 空 / 0 震荡）
        """
        cfg = self.cfg

        # 用 15m resample 成 4h
        ohlc_4h = df_15m[["open", "high", "low", "close"]].resample("4H").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
            }
        ).dropna()

        macd_4h, sig_4h, hist_4h = self._calc_macd(
            ohlc_4h["close"], cfg.macd_fast, cfg.macd_slow, cfg.macd_signal
        )
        rsi_4h = self._calc_rsi(ohlc_4h["close"], cfg.rsi_period)

        trend_4h = pd.Series(0, index=ohlc_4h.index, dtype="int8")

        # 多头趋势：MACD 多头 + 柱 > 0 + RSI > 阈值
        long_trend = (macd_4h > sig_4h) & (hist_4h > 0) & (rsi_4h > cfg.rsi_trend_high)

        # 空头趋势：MACD 空头 + 柱 < 0 + RSI < 阈值
        short_trend = (macd_4h < sig_4h) & (hist_4h < 0) & (rsi_4h < cfg.rsi_trend_low)

        trend_4h[long_trend] = 1
        trend_4h[short_trend] = -1

        # 对齐回 15m 时间轴，向前填充
        trend_15m = trend_4h.reindex(df_15m.index, method="ffill").fillna(0).astype("int8")
        return trend_15m

    # ========= 主策略：生成信号 =========
    def generate_signals(self, df_15m: pd.DataFrame) -> pd.DataFrame:
        """
        df_15m:
            index: DatetimeIndex (频率 = 15m)，必须升序
            columns: open, high, low, close, volume（volume 可选）
        返回：
            在原 df 基础上增加：
            trend_4h, ema200_15m,
            macd_15m, macd_signal_15m, macd_hist_15m,
            rsi_15m, atr_15m,
            entry_long, entry_short, sl_price, tp1_price, signal
        """
        cfg = self.cfg
        df = df_15m.sort_index().copy()

        # 4h 趋势
        df["trend_4h"] = self._calc_trend_4h(df)

        # 15m EMA200（结构过滤）
        df["ema200_15m"] = df["close"].ewm(span=200, adjust=False).mean()

        # 15m MACD
        macd_15m, sig_15m, hist_15m = self._calc_macd(
            df["close"], cfg.macd_fast, cfg.macd_slow, cfg.macd_signal
        )
        df["macd_15m"] = macd_15m
        df["macd_signal_15m"] = sig_15m
        df["macd_hist_15m"] = hist_15m

        # 15m RSI
        df["rsi_15m"] = self._calc_rsi(df["close"], cfg.rsi_period)

        # 15m ATR
        df["atr_15m"] = self._calc_atr(df, cfg.atr_period)

        # 回调确认：过去 N 根 K 内 RSI 最低 & 最高
        rsi_min = df["rsi_15m"].rolling(cfg.lookback_bars, min_periods=1).min()
        rsi_max = df["rsi_15m"].rolling(cfg.lookback_bars, min_periods=1).max()

        # ===== 多头入场条件 =====
        long_trend = df["trend_4h"] == 1
        price_above_ema = df["close"] > df["ema200_15m"]

        # RSI 从下向上穿越 entry_upper，且过去一段时间有过回调（rsi_min <= entry_lower）
        rsi_cross_up = (df["rsi_15m"] > cfg.rsi_entry_upper) & (
            df["rsi_15m"].shift(1) <= cfg.rsi_entry_upper
        )
        rsi_had_pullback = rsi_min <= cfg.rsi_entry_lower

        # MACD 在 15m 上金叉并转多
        macd_bull = (
            (df["macd_15m"] > df["macd_signal_15m"])
            & (df["macd_15m"].shift(1) <= df["macd_signal_15m"].shift(1))
            & (df["macd_hist_15m"] > 0)
        )

        entry_long = (long_trend & price_above_ema & rsi_cross_up & rsi_had_pullback & macd_bull)

        # ===== 空头入场条件 =====
        short_trend = df["trend_4h"] == -1
        price_below_ema = df["close"] < df["ema200_15m"]

        # RSI 从上向下穿越 entry_lower，且过去一段时间有过反弹（rsi_max >= entry_upper）
        rsi_cross_down = (df["rsi_15m"] < cfg.rsi_entry_lower) & (
            df["rsi_15m"].shift(1) >= cfg.rsi_entry_lower
        )
        rsi_had_rebound = rsi_max >= cfg.rsi_entry_upper

        # MACD 在 15m 上死叉并转空
        macd_bear = (
            (df["macd_15m"] < df["macd_signal_15m"])
            & (df["macd_15m"].shift(1) >= df["macd_signal_15m"].shift(1))
            & (df["macd_hist_15m"] < 0)
        )

        entry_short = (short_trend & price_below_ema & rsi_cross_down & rsi_had_rebound & macd_bear)

        df["entry_long"] = entry_long.astype("int8")
        df["entry_short"] = entry_short.astype("int8")

        # ===== 按 ATR 计算止损 & 第一个止盈（2R） =====
        df["sl_price"] = np.nan
        df["tp1_price"] = np.nan

        # 多单
        long_idx = df["entry_long"] == 1
        atr_long = df.loc[long_idx, "atr_15m"]
        close_long = df.loc[long_idx, "close"]
        sl_long = close_long - cfg.atr_sl_mult * atr_long
        # 1R = close_long - sl_long；tp1 = close_long + 2R
        tp1_long = close_long + 2 * (close_long - sl_long)

        df.loc[long_idx, "sl_price"] = sl_long
        df.loc[long_idx, "tp1_price"] = tp1_long

        # 空单
        short_idx = df["entry_short"] == 1
        atr_short = df.loc[short_idx, "atr_15m"]
        close_short = df.loc[short_idx, "close"]
        sl_short = close_short + cfg.atr_sl_mult * atr_short
        # 1R = sl_short - close_short；tp1 = close_short - 2R
        tp1_short = close_short - 2 * (sl_short - close_short)

        df.loc[short_idx, "sl_price"] = sl_short
        df.loc[short_idx, "tp1_price"] = tp1_short

        # 总体方向信号：1 = 开多，-1 = 开空，0 = 不动
        df["signal"] = df["entry_long"].astype(int) - df["entry_short"].astype(int)

        return df

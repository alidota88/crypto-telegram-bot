
# -*- coding: utf-8 -*-
from dataclasses import dataclass
import pandas as pd
import numpy as np

def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def macd(series: pd.Series, fast: int, slow: int, signal: int):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False).mean()
    hist = line - sig
    return line, sig, hist

def rsi(series: pd.Series, period: int):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / (avg_loss.replace(0, np.nan))
    out = 100 - (100 / (1 + rs))
    return out

def atr(df: pd.DataFrame, period: int):
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()

def resample_ohlc(df_15m: pd.DataFrame, rule: str) -> pd.DataFrame:
    ohlc = df_15m.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        **({"volume": "sum"} if "volume" in df_15m.columns else {})
    }).dropna()
    return ohlc

@dataclass
class MultiTFConfig:
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    ema_fast: int = 21
    ema_slow: int = 55
    ema_pulback: int = 89
    rsi_period: int = 14
    atr_period: int = 14
    rsi_trend_high: float = 55.0
    rsi_trend_low: float = 45.0
    rsi_reentry_up: float = 50.0
    rsi_reentry_dn: float = 50.0
    rsi_pullback_long: float = 45.0
    rsi_pullback_short: float = 55.0
    lookback_pullback_bars_1h: int = 36
    lookback_break_15m: int = 20
    atr_sl_mult: float = 2.5
    rr_tp1: float = 2.0
    align_method: str = "ffill"

class MultiTFMidtermStrategy:
    def __init__(self, cfg: MultiTFConfig | None = None):
        self.cfg = cfg or MultiTFConfig()

    def _compute_higher_tfs(self, df_15m: pd.DataFrame):
        cfg = self.cfg
        df_1h  = resample_ohlc(df_15m, "1H")
        df_4h  = resample_ohlc(df_15m, "4H")
        df_1d  = resample_ohlc(df_15m, "1D")

        d_macd, d_sig, d_hist = macd(df_1d["close"], cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
        trend_1d = pd.Series(0, index=df_1d.index, dtype="int8")
        trend_1d[(d_macd > d_sig) & (d_hist > 0)] = 1
        trend_1d[(d_macd < d_sig) & (d_hist < 0)] = -1

        h4_macd, h4_sig, h4_hist = macd(df_4h["close"], cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
        h4_rsi = rsi(df_4h["close"], cfg.rsi_period)
        h4_ema_fast = ema(df_4h["close"], cfg.ema_fast)
        h4_ema_slow = ema(df_4h["close"], cfg.ema_slow)

        trend_4h = pd.Series(0, index=df_4h.index, dtype="int8")
        long_ok = (h4_macd > h4_sig) & (h4_hist > 0) & (h4_rsi > cfg.rsi_trend_high) & (h4_ema_fast > h4_ema_slow)
        short_ok = (h4_macd < h4_sig) & (h4_hist < 0) & (h4_rsi < cfg.rsi_trend_low) & (h4_ema_fast < h4_ema_slow)
        trend_4h[long_ok] = 1
        trend_4h[short_ok] = -1

        h1_macd, h1_sig, h1_hist = macd(df_1h["close"], cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
        h1_rsi = rsi(df_1h["close"], cfg.rsi_period)
        h1_ema_fast = ema(df_1h["close"], cfg.ema_fast)
        h1_ema_slow = ema(df_1h["close"], cfg.ema_slow)
        h1_ema_pb   = ema(df_1h["close"], cfg.ema_pulback)
        h1_atr = atr(df_1h, cfg.atr_period)

        def align_to_15m(s: pd.Series) -> pd.Series:
            return s.reindex(df_15m.index, method=cfg.align_method).astype(s.dtype)

        aligned = {
            "trend_1d": align_to_15m(trend_1d),
            "trend_4h": align_to_15m(trend_4h),
            "h1_close": align_to_15m(df_1h["close"]),
            "h1_macd": align_to_15m(h1_macd),
            "h1_sig": align_to_15m(h1_sig),
            "h1_hist": align_to_15m(h1_hist),
            "h1_rsi": align_to_15m(h1_rsi),
            "h1_ema_fast": align_to_15m(h1_ema_fast),
            "h1_ema_slow": align_to_15m(h1_ema_slow),
            "h1_ema_pb": align_to_15m(h1_ema_pb),
            "h1_atr": align_to_15m(h1_atr),
            "h4_macd": align_to_15m(h4_macd),
            "h4_sig": align_to_15m(h4_sig),
            "h4_hist": align_to_15m(h4_hist),
            "h4_rsi": align_to_15m(h4_rsi),
            "h4_ema_fast": align_to_15m(h4_ema_fast),
            "h4_ema_slow": align_to_15m(h4_ema_slow),
        }
        return aligned

    def generate_signals(self, df_15m: pd.DataFrame) -> pd.DataFrame:
        cfg = self.cfg
        df = df_15m.sort_index().copy()
        hi = self._compute_higher_tfs(df)

        df['ema_fast_15m'] = ema(df['close'], cfg.ema_fast)
        df['ema_slow_15m'] = ema(df['close'], cfg.ema_slow)
        df['rsi_15m']      = rsi(df['close'], cfg.rsi_period)

        highest_prev = df['high'].rolling(cfg.lookback_break_15m, min_periods=1).max().shift(1)
        lowest_prev  = df['low'].rolling(cfg.lookback_break_15m, min_periods=1).min().shift(1)

        df['trend_1d'] = hi['trend_1d']
        df['trend_4h'] = hi['trend_4h']

        rsi1h = hi['h1_rsi']
        h1_rsi_pullback_done = rsi1h.rolling(cfg.lookback_pullback_bars_1h, min_periods=1).min() <= cfg.rsi_pullback_long
        h1_rsi_cross_up = (rsi1h > cfg.rsi_reentry_up) & (rsi1h.shift(1) <= cfg.rsi_reentry_up)
        h1_macd_cross_up = (hi['h1_macd'] > hi['h1_sig']) & (hi['h1_macd'].shift(1) <= hi['h1_sig'].shift(1))
        h1_close = hi['h1_close']
        near_ratio = 0.005
        h1_touched_slow = (
            ((h1_close - hi['h1_ema_slow']).abs() / h1_close <= near_ratio) |
            ((h1_close - hi['h1_ema_pb']).abs() / h1_close <= near_ratio)
        )
        confirm_1h_long = (
            (hi['trend_1d'] == 1) & (hi['trend_4h'] == 1) &
            h1_rsi_pullback_done & h1_rsi_cross_up & h1_macd_cross_up & h1_touched_slow
        )

        h1_rsi_rebound_done = rsi1h.rolling(cfg.lookback_pullback_bars_1h, min_periods=1).max() >= cfg.rsi_pullback_short
        h1_rsi_cross_dn = (rsi1h < cfg.rsi_reentry_dn) & (rsi1h.shift(1) >= cfg.rsi_reentry_dn)
        h1_macd_cross_dn = (hi['h1_macd'] < hi['h1_sig']) & (hi['h1_macd'].shift(1) >= hi['h1_sig'].shift(1))
        confirm_1h_short = (
            (hi['trend_1d'] == -1) & (hi['trend_4h'] == -1) &
            h1_rsi_rebound_done & h1_rsi_cross_dn & h1_macd_cross_dn & h1_touched_slow
        )

        df['confirm_1h_long'] = confirm_1h_long.astype('int8')
        df['confirm_1h_short'] = confirm_1h_short.astype('int8')

        cross_up_15m = (df['ema_fast_15m'] > df['ema_slow_15m']) & (df['ema_fast_15m'].shift(1) <= df['ema_slow_15m'].shift(1))
        cross_dn_15m = (df['ema_fast_15m'] < df['ema_slow_15m']) & (df['ema_fast_15m'].shift(1) >= df['ema_slow_15m'].shift(1))
        rsi_up_15m = (df['rsi_15m'] > cfg.rsi_reentry_up) & (df['rsi_15m'].shift(1) <= cfg.rsi_reentry_up)
        rsi_dn_15m = (df['rsi_15m'] < cfg.rsi_reentry_dn) & (df['rsi_15m'].shift(1) >= cfg.rsi_reentry_dn)
        highest_prev = highest_prev.fillna(method='ffill')
        lowest_prev = lowest_prev.fillna(method='ffill')
        break_up_15m = df['close'] > highest_prev
        break_dn_15m = df['close'] < lowest_prev

        trigger_15m_long = confirm_1h_long & cross_up_15m & rsi_up_15m & break_up_15m
        trigger_15m_short = confirm_1h_short & cross_dn_15m & rsi_dn_15m & break_dn_15m

        df['trigger_15m_long'] = trigger_15m_long.astype('int8')
        df['trigger_15m_short'] = trigger_15m_short.astype('int8')
        df['signal'] = df['trigger_15m_long'].astype(int) - df['trigger_15m_short'].astype(int)

        df['sl_price'] = np.nan
        df['tp1_price'] = np.nan
        atr_1h = hi['h1_atr']
        close_15m = df['close']

        long_idx = df['signal'] == 1
        sl_long = close_15m[long_idx] - cfg.atr_sl_mult * atr_1h[long_idx]
        tp1_long = close_15m[long_idx] + cfg.rr_tp1 * (close_15m[long_idx] - sl_long)
        df.loc[long_idx, 'sl_price'] = sl_long
        df.loc[long_idx, 'tp1_price'] = tp1_long

        short_idx = df['signal'] == -1
        sl_short = close_15m[short_idx] + cfg.atr_sl_mult * atr_1h[short_idx]
        tp1_short = close_15m[short_idx] - cfg.rr_tp1 * (sl_short - close_15m[short_idx])
        df.loc[short_idx, 'sl_price'] = sl_short
        df.loc[short_idx, 'tp1_price'] = tp1_short

        return df

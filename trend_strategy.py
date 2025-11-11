"""Hourly trend-only strategy used for broadcast messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

TrendLabel = Literal["strong_bull", "bull", "neutral", "bear", "strong_bear"]


@dataclass
class TrendResult:
    symbol: str
    price: float
    ema_fast: float
    ema_slow: float
    rsi: float
    slope: float
    label: TrendLabel

    def format_message(self) -> str:
        trend_map = {
            "strong_bull": "🚀 强势多头",
            "bull": "📈 多头",
            "neutral": "⚖️ 震荡",
            "bear": "📉 空头",
            "strong_bear": "🔥 强势空头",
        }
        status = trend_map[self.label]
        return (
            f"{self.symbol} 当前价 {self.price:.2f} USDT\n"
            f"趋势判断：{status}\n"
            f"EMA20={self.ema_fast:.2f}, EMA50={self.ema_slow:.2f}, RSI={self.rsi:.1f},"
            f" 近5小时斜率={self.slope:.2f}"
        )


class HourlyTrendStrategy:
    """Use hourly EMAs + RSI to classify medium-term trend bias."""

    def __init__(
        self,
        fast_period: int = 20,
        slow_period: int = 50,
        rsi_period: int = 14,
        slope_window: int = 5,
    ) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.rsi_period = rsi_period
        self.slope_window = slope_window

    def _calc_rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.rolling(self.rsi_period, min_periods=self.rsi_period).mean()
        avg_loss = loss.rolling(self.rsi_period, min_periods=self.rsi_period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def evaluate(self, symbol: str, df_1h: pd.DataFrame) -> TrendResult:
        df = df_1h.sort_index().copy()
        close = df["close"]

        ema_fast = close.ewm(span=self.fast_period, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow_period, adjust=False).mean()
        rsi = self._calc_rsi(close)

        price = float(close.iloc[-1])
        ema_fast_last = float(ema_fast.iloc[-1])
        ema_slow_last = float(ema_slow.iloc[-1])
        rsi_last = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else float("nan")

        slope_window = min(self.slope_window, len(ema_fast) - 1)
        if slope_window <= 0:
            slope = 0.0
        else:
            slope = float(ema_fast.iloc[-1] - ema_fast.iloc[-1 - slope_window])

        label: TrendLabel
        if (
            price > ema_fast_last
            and ema_fast_last > ema_slow_last
            and rsi_last >= 60
            and slope >= 0
        ):
            label = "strong_bull"
        elif price > ema_fast_last and ema_fast_last >= ema_slow_last:
            label = "bull"
        elif (
            price < ema_fast_last
            and ema_fast_last < ema_slow_last
            and rsi_last <= 40
            and slope <= 0
        ):
            label = "strong_bear"
        elif price < ema_fast_last and ema_fast_last <= ema_slow_last:
            label = "bear"
        else:
            label = "neutral"

        return TrendResult(
            symbol=symbol,
            price=price,
            ema_fast=ema_fast_last,
            ema_slow=ema_slow_last,
            rsi=rsi_last if not pd.isna(rsi_last) else 50.0,
            slope=slope,
            label=label,
        )

    def build_report(self, symbols: list[str], data_loader) -> str:
        lines = ["[小时级趋势播报]"]
        for symbol in symbols:
            try:
                df = data_loader(symbol)
                if df.empty:
                    raise ValueError("无可用的 K 线数据")
                result = self.evaluate(symbol, df)
                lines.append(result.format_message())
            except Exception as exc:  # pragma: no cover - 网络/数据异常
                lines.append(f"{symbol} 趋势计算失败：{exc}")
        return "\n\n".join(lines)

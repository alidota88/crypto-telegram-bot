"""Runtime bridge between strategies and Telegram broadcast jobs."""

from __future__ import annotations

from typing import List, Tuple

from market_service import fetch_klines
from trend_strategy import HourlyTrendStrategy

TRADE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

hourly_trend_strategy = HourlyTrendStrategy()


def run_strategy_and_update_positions() -> Tuple[str, List[str]]:
    """Execute the hourly trend scan and return the formatted broadcast message."""

    def load_hourly(symbol: str):
        return fetch_klines(symbol, interval="1h", limit=300)

    report = hourly_trend_strategy.build_report(TRADE_SYMBOLS, data_loader=load_hourly)
    return report, [report]

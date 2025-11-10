from typing import List, Dict
import requests
import pandas as pd

BINANCE_BASE = "https://api.binance.com"


def get_price(symbol: str) -> float:
    """获取单个交易对现价，例如 BTCUSDT"""
    url = f"{BINANCE_BASE}/api/v3/ticker/price"
    resp = requests.get(url, params={"symbol": symbol.upper()}, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    return float(data["price"])


def get_market_snapshot(symbols: List[str]) -> Dict[str, float]:
    """一次性获取多个交易对价格"""
    return {sym: get_price(sym) for sym in symbols}


def fetch_15m_klines(symbol: str, limit: int = 300) -> pd.DataFrame:
    """
    从 Binance 获取 15m K 线，并转成 DataFrame:
    index = 时间（DatetimeIndex）
    columns = open, high, low, close, volume
    """
    url = f"{BINANCE_BASE}/api/v3/klines"
    params = {
        "symbol": symbol.upper(),
        "interval": "15m",
        "limit": limit,
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    df = pd.DataFrame(
        data,
        columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ],
    )
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df.set_index("open_time", inplace=True)
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df.index = df.index.sort_values()
    return df

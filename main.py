import os
import logging
import requests
from typing import List, Dict

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# 从环境变量里读取 Telegram Bot 的 Token（在 Railway 里配置）
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ========= 全局订阅表（简单版：内存里存一份） =========
PRICE_SUBSCRIBERS: set[int] = set()
STRATEGY_SUBSCRIBERS: set[int] = set()


# ========= 行情相关函数（你以后可以单独拆到 market_service.py） =========

BINANCE_URL = "https://api.binance.com/api/v3/ticker/price"


def get_price(symbol: str) -> float:
    """获取任意交易对现价，例如 BTCUSDT / ETHUSDT"""
    resp = requests.get(
        BINANCE_URL,
        params={"symbol": symbol.upper()},
        timeout=5,
    )
    resp.raise_for_status()
    data = resp.json()
    return float(data["price"])


def get_market_snapshot(symbols: List[str]) -> Dict[str, float]:
    """一次性获取多币种价格"""
    return {sym: get_price(sym) for sym in symbols}


# ========= 策略信号相关函数（以后你可换成自己策略引擎） =========

def get_demo_strategy_signals() -> List[Dict]:
    """
    这里先写一个“演示版策略信号”：
    实际使用时你可以改成：
      - 调你自己的 HTTP 接口
      - 读数据库 / 文件
      - 直接在这里写筛选逻辑
    """
    # 没有信号时可以返回空列表 []
    return [
        {
            "symbol": "BTCUSDT",
            "direction": "多头",
            "entry": 68000,
            "stop": 66000,
            "target": 72000,
            "reason": "演示信号：突破 20 日高点，量能放大",
        },
        {
            "symbol": "ETHUSDT",
            "direction": "空头",
            "entry": 3800,
            "stop": 3950,
            "target": 3500,
            "reason": "演示信号：跌破趋势线，MACD 死叉",
        },
    ]


def format_signals_text(signals: List[Dict]) -> str:
    if not signals:
        return "当前没有新的策略信号。"

    lines = ["[策略筛选信号]"]
    for s in signals:
        line = (
            f"{s['symbol']} | {s['direction']}\n"
            f"  入场: {s['entry']}\n"
            f"  止损: {s['stop']}  止盈: {s['target']}\n"
            f"  原因: {s['reason']}\n"
        )
        lines.append(line)
    return "\n".join(lines)


# ========= 命令处理函数（handlers） =========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.eff

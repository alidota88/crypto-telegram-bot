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
    user = update.effective_user
    text = (
        f"你好，{user.first_name or '朋友'}！\n"
        "我是你的 Crypto Assistant 机器人。\n\n"
        "基础命令：\n"
        "/price       - 查看 BTC 当前价格\n"
        "/market      - 查看 BTC & ETH 简要行情\n\n"
        "订阅相关：\n"
        "/sub_price   - 订阅定时行情推送\n"
        "/unsub_price - 取消定时行情推送\n"
        "/sub_strategy   - 订阅策略筛选信号推送\n"
        "/unsub_strategy - 取消策略信号推送\n"
    )
    await update.message.reply_text(text)


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        p = get_price("BTCUSDT")
        await update.message.reply_text(f"当前 BTC/USDT 价格约为：{p:.2f} USDT")
    except Exception:
        logger.exception("获取 BTC 价格失败")
        await update.message.reply_text("获取 BTC 价格失败，请稍后再试。")


async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        snapshot = get_market_snapshot(["BTCUSDT", "ETHUSDT"])
        text_lines = ["[简要行情]"]
        for sym, price_ in snapshot.items():
            text_lines.append(f"{sym}: {price_:.2f} USDT")
        await update.message.reply_text("\n".join(text_lines))
    except Exception:
        logger.exception("获取行情失败")
        await update.message.reply_text("获取行情失败，请稍后再试。")


# ---- 订阅 & 取消订阅行情推送 ----
async def sub_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    PRICE_SUBSCRIBERS.add(chat_id)
    await update.message.reply_text("已订阅：定时行情推送。")


async def unsub_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    PRICE_SUBSCRIBERS.discard(chat_id)
    await update.message.reply_text("已取消：定时行情推送。")


# ---- 订阅 & 取消订阅策略信号推送 ----
async def sub_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    STRATEGY_SUBSCRIBERS.add(chat_id)
    await update.message.reply_text("已订阅：策略筛选信号推送。")


async def unsub_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    STRATEGY_SUBSCRIBERS.discard(chat_id)
    await update.message.reply_text("已取消：策略筛选信号推送。")


# ========= 定时任务（JobQueue 回调） =========

async def job_push_price(context: ContextTypes.DEFAULT_TYPE):
    """定时给订阅用户推送行情"""
    if not PRICE_SUBSCRIBERS:
        return

    try:
        snapshot = get_market_snapshot(["BTCUSDT", "ETHUSDT"])
        text_lines = ["[定时行情推送]"]
        for sym, price_ in snapshot.items():
            text_lines.append(f"{sym}: {price_:.2f} USDT")
        text = "\n".join(text_lines)

        for chat_id in list(PRICE_SUBSCRIBERS):
            await context.application.bot.send_message(chat_id=chat_id, text=text)
    except Exception:
        logger.exception("定时行情推送失败")


async def job_push_strategy(context: ContextTypes.DEFAULT_TYPE):
    """定时给订阅用户推送策略筛选信号"""
    if not STRATEGY_SUBSCRIBERS:
        return

    try:
        signals = get_demo_strategy_signals()
        text = format_signals_text(signals)

        for chat_id in list(STRATEGY_SUBSCRIBERS):
            await context.application.bot.send_message(chat_id=chat_id, text=text)
    except Exception:
        logger.exception("定时策略推送失败")


# ========= 程序入口 =========

def main():
    if not TOKEN:
        raise RuntimeError("环境变量 TELEGRAM_BOT_TOKEN 没有设置！")

    application = Application.builder().token(TOKEN).build()

    # 命令注册
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("market", market))

    application.add_handler(CommandHandler("sub_price", sub_price))
    application.add_handler(CommandHandler("unsub_price", unsub_price))

    application.add_handler(CommandHandler("sub_strategy", sub_strategy))
    application.add_handler(CommandHandler("unsub_strategy", unsub_strategy))

    # 定时任务（JobQueue）
    jq = application.job_queue
    # 每 10 分钟推一次行情（你可以改成 60 * 60 = 1 小时等）
    jq.run_repeating(job_push_price, interval=10 * 60, first=30, name="price_push")
    # 每 15 分钟推一次策略信号（演示）
    jq.run_repeating(job_push_strategy, interval=15 * 60, first=60, name="strategy_push")

    logger.info("🤖 Bot 已启动，开始轮询 Telegram 消息...")
    application.run_polling()


if __name__ == "__main__":
    main()

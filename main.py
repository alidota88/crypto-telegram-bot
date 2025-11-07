import os
import logging
import requests
from typing import List, Dict
from dataclasses import dataclass

import pandas as pd
import numpy as np
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from macd_rsi_strategy import MACDRSIStrategy  # 引用你的策略类

# 从环境变量里读取 Telegram Bot 的 Token（在 Railway 里配置）
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ======= 模拟资金与仓位管理 =======
TOTAL_CAPITAL = 10_000.0      # 总资金（仅做显示，不做严格风控）
PER_TRADE_NOTIONAL = 2_000.0  # 每个品种固定 2000 USDT

TRADE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


@dataclass
class Position:
    symbol: str
    side: str           # "long" or "short"
    entry_price: float
    qty: float
    notional: float
    realized_pnl: float = 0.0


# 当前持仓（内存简单版）
POSITIONS: Dict[str, Position] = {}

# 实现盈亏累计
TOTAL_REALIZED_PNL: float = 0.0

# 策略实例（全局用一个）
strategy = MACDRSIStrategy()

BINANCE_BASE = "https://api.binance.com"


def fetch_15m_klines(symbol: str, limit: int = 300) -> pd.DataFrame:
    """
    从 Binance 获取 15m K 线，并转成 DataFrame:
    index = 时间（DatetimeIndex, freq=15min 升序）
    columns = open, high, low, close, volume
    """
    url = f"{BINANCE_BASE}/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": "15m",
        "limit": limit,
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    # kline 结构: [open_time, open, high, low, close, volume, close_time, ...]
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

# ========= 全局订阅表（简单版：内存里存一份） =========
PRICE_SUBSCRIBERS: set[int] = set()
STRATEGY_SUBSCRIBERS: set[int] = set()

def run_strategy_and_update_positions() -> str:
    """
    对 TRADE_SYMBOLS 逐个跑策略，更新模拟持仓 & 计算盈亏，
    返回一段适合发到 Telegram 的文本。
    """
    global TOTAL_REALIZED_PNL

    lines: List[str] = []
    lines.append("[策略信号 + 仓位模拟（每小时）]")
    lines.append(f"总资金假设: {TOTAL_CAPITAL:.2f} USDT, 每个品种开仓: {PER_TRADE_NOTIONAL:.2f} USDT\n")

    for symbol in TRADE_SYMBOLS:
        try:
            df_15m = fetch_15m_klines(symbol, limit=300)
            df_sig = strategy.generate_signals(df_15m)
            last = df_sig.iloc[-1]
            last_price = float(last["close"])
            signal = int(last["signal"])  # 1=多, -1=空, 0=无操作

            pos = POSITIONS.get(symbol)
            symbol_line: List[str] = [f"{symbol} 当前价: {last_price:.4f}"]

            # 1) 如果有持仓，先计算浮动盈亏
            unreal_pnl = 0.0
            if pos is not None:
                if pos.side == "long":
                    unreal_pnl = (last_price - pos.entry_price) * pos.qty
                else:
                    unreal_pnl = (pos.entry_price - last_price) * pos.qty

            # 2) 信号逻辑：先平后开（简单版）
            # 平仓条件：已有仓位 && (信号反向 或 signal == 0)
            if pos is not None and (signal == 0 or (signal == 1 and pos.side == "short") or (signal == -1 and pos.side == "long")):
                # 以当前价格平仓
                if pos.side == "long":
                    realized = (last_price - pos.entry_price) * pos.qty
                else:
                    realized = (pos.entry_price - last_price) * pos.qty

                pos.realized_pnl += realized
                TOTAL_REALIZED_PNL += realized
                symbol_line.append(
                    f"平仓: {pos.side.upper()} @ {last_price:.4f}, "
                    f"本次盈亏: {realized:.2f} USDT, 累计: {pos.realized_pnl:.2f} USDT"
                )
                # 清掉持仓
                POSITIONS[symbol] = None

                pos = None
                unreal_pnl = 0.0

            # 3) 开仓条件：当前无仓 && 信号 != 0
            if pos is None and signal != 0:
                side = "long" if signal == 1 else "short"
                notional = PER_TRADE_NOTIONAL
                qty = notional / last_price

                pos = Position(
                    symbol=symbol,
                    side=side,
                    entry_price=last_price,
                    qty=qty,
                    notional=notional,
                )
                POSITIONS[symbol] = pos

                symbol_line.append(
                    f"开仓: {side.upper()} @ {last_price:.4f}, "
                    f"名义资金: {notional:.2f} USDT, 数量: {qty:.6f}"
                )

            # 4) 如果现在有仓位，报告当前浮盈/浮亏
            pos = POSITIONS.get(symbol)
            if pos is not None:
                if pos.side == "long":
                    unreal_pnl = (last_price - pos.entry_price) * pos.qty
                else:
                    unreal_pnl = (pos.entry_price - last_price) * pos.qty

                symbol_line.append(
                    f"持仓: {pos.side.upper()} @ {pos.entry_price:.4f}, "
                    f"浮动盈亏: {unreal_pnl:.2f} USDT, 累计已实现: {pos.realized_pnl:.2f} USDT"
                )
            else:
                symbol_line.append("当前无持仓")

            lines.append("\n".join(symbol_line))
            lines.append("")  # 空行分隔
        except Exception as e:
            logger.exception("运行策略失败: %s", symbol)
            lines.append(f"{symbol}: 运行策略失败：{e}")

    lines.append(f"\n组合累计已实现盈亏: {TOTAL_REALIZED_PNL:.2f} USDT")
    return "\n".join(lines)

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
    """每小时推送一次：策略信号 + 仓位盈亏"""
    try:
        text = run_strategy_and_update_positions()
    except Exception:
        logger.exception("策略任务失败")
        text = "策略任务运行失败，请查看日志。"

    # 给所有订阅了策略的用户推送（用你之前的 STRATEGY_SUBSCRIBERS）
    if not STRATEGY_SUBSCRIBERS:
        return

    for chat_id in list(STRATEGY_SUBSCRIBERS):
        try:
            await context.application.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception("发送策略推送失败 chat_id=%s", chat_id)



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

    if jq is None:
        logger.warning(
            "JobQueue 未启用，定时推送功能不可用。"
            "请确认 requirements.txt 中安装的是 python-telegram-bot[job-queue]>=20.0"
        )
    else:
        # 行情推送（你之前的）
        jq.run_repeating(
            job_push_price,
            interval=10 * 60,
            first=30,
            name="price_push",
        )
        # 策略推送：每小时一次，首次延迟 120 秒
        jq.run_repeating(
            job_push_strategy,
            interval=60 * 60,
            first=120,
            name="strategy_push",
        )


    logger.info("🤖 Bot 已启动，开始轮询 Telegram 消息...")
    application.run_polling()


if __name__ == "__main__":
    main()

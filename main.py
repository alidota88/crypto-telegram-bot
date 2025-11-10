import os
import logging
from typing import Set

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from market_service import get_price, get_market_snapshot
from trading_engine import run_strategy_and_update_positions

# 从环境变量里读取 Telegram Bot 的 Token（在 Railway 配置）
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# 订阅集合
PRICE_SUBSCRIBERS: Set[int] = set()
STRATEGY_SUBSCRIBERS: Set[int] = set()


# ========= 命令处理 =========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"你好，{user.first_name or '朋友'}！\n"
        "我是你的 Crypto Assistant 机器人。\n\n"
        "基础命令：\n"
        "/price       - 查看 BTC 当前价格\n"
        "/market      - 查看 BTC & ETH 简要行情\n\n"
        "订阅相关：\n"
        "/sub_price      - 订阅定时行情推送\n"
        "/unsub_price    - 取消定时行情推送\n"
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
        lines = ["[简要行情]"]
        for sym, price_ in snapshot.items():
            lines.append(f"{sym}: {price_:.2f} USDT")
        await update.message.reply_text("\n".join(lines))
    except Exception:
        logger.exception("获取行情失败")
        await update.message.reply_text("获取行情失败，请稍后再试。")


async def sub_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    PRICE_SUBSCRIBERS.add(chat_id)
    await update.message.reply_text("已订阅：定时行情推送。")


async def unsub_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    PRICE_SUBSCRIBERS.discard(chat_id)
    await update.message.reply_text("已取消：定时行情推送。")


async def sub_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    STRATEGY_SUBSCRIBERS.add(chat_id)
    await update.message.reply_text("已订阅：策略筛选信号推送。")


async def unsub_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    STRATEGY_SUBSCRIBERS.discard(chat_id)
    await update.message.reply_text("已取消：策略筛选信号推送。")


# ========= 定时任务 =========

async def job_push_strategy(context: ContextTypes.DEFAULT_TYPE):
    """定时跑一轮策略，有开仓/平仓事件就立刻推送"""
    if not STRATEGY_SUBSCRIBERS:
        return

    try:
        summary_text, trade_events = run_strategy_and_update_positions()
    except Exception:
        logger.exception("策略任务失败")
        return

    # 没有新开仓/平仓，就不推送，避免打扰
    if not trade_events:
        return

    # 有订阅的人，每人推送本次所有新事件
    for chat_id in list(STRATEGY_SUBSCRIBERS):
        for msg in trade_events:
            try:
                await context.application.bot.send_message(chat_id=chat_id, text=msg)
            except Exception:
                logger.exception("发送策略推送失败 chat_id=%s", chat_id)

    # 如果你以后想顺带推送 summary，可以在这里追加一条：
    # for chat_id in list(STRATEGY_SUBSCRIBERS):
    #     await context.application.bot.send_message(chat_id=chat_id, text=summary_text)



async def job_push_strategy(context: ContextTypes.DEFAULT_TYPE):
    """定时给订阅用户推策略信号 + 模拟盈亏"""
    if not STRATEGY_SUBSCRIBERS:
        return

    try:
        text = run_strategy_and_update_positions()
    except Exception:
        logger.exception("策略任务失败")
        text = "策略任务运行失败，请查看日志。"

    for chat_id in list(STRATEGY_SUBSCRIBERS):
        try:
            await context.application.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception("发送策略推送失败 chat_id=%s", chat_id)


# ========= 入口 =========

def main():
    if not TOKEN:
        raise RuntimeError("环境变量 TELEGRAM_BOT_TOKEN 没有设置！")

    application = Application.builder().token(TOKEN).build()

    # 注册命令
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CommandHandler("market", market))
    application.add_handler(CommandHandler("sub_price", sub_price))
    application.add_handler(CommandHandler("unsub_price", unsub_price))
    application.add_handler(CommandHandler("sub_strategy", sub_strategy))
    application.add_handler(CommandHandler("unsub_strategy", unsub_strategy))

    # 注册 JobQueue
    jq = application.job_queue
    if jq is None:
        logger.warning(
            "JobQueue 未启用，定时推送功能不可用。"
            "请确认 requirements.txt 中安装的是 python-telegram-bot[job-queue]>=20.0"
        )
    else:
        # 行情：每 10 分钟推一次
        jq.run_repeating(
            job_push_price,
            interval=10 * 60,
            first=30,
            name="price_push",
        )
        # 策略：每小时推一次（调试时可以改小）
        jq.run_repeating(
            job_push_strategy,
            interval=60,      # 每 60 秒跑一轮策略
            first=30,         # 启动后 30 秒跑第一轮
            name="strategy_push",
        )


    logger.info("🤖 Bot 已启动，开始轮询 Telegram 消息...")
    application.run_polling()


if __name__ == "__main__":
    main()

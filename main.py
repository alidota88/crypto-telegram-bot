import os
import logging
import requests
from telegram.ext import Updater, CommandHandler

# 从环境变量里读取 Telegram Bot 的 Token（稍后在 Railway 里配置）
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def get_btc_price():
    """从 Binance 公共 API 获取 BTCUSDT 现价"""
    url = "https://api.binance.com/api/v3/ticker/price"
    params = {"symbol": "BTCUSDT"}
    resp = requests.get(url, params=params, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    return float(data["price"])


def start(update, context):
    user = update.effective_user
    text = (
        f"你好，{user.first_name or '朋友'}！\n"
        "我是你的 Crypto Assistant 机器人。\n\n"
        "目前支持的命令：\n"
        "/price - 查看 BTC 当前价格\n"
    )
    update.message.reply_text(text)


def price(update, context):
    try:
        p = get_btc_price()
        update.message.reply_text(f"当前 BTC/USDT 价格约为：{p:.2f} USDT")
    except Exception as e:
        logger.exception("获取价格失败")
        update.message.reply_text("获取价格失败，请稍后再试。")


def main():
    if not TOKEN:
        raise RuntimeError("环境变量 TELEGRAM_BOT_TOKEN 没有设置！")

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("price", price))

    logger.info("🤖 Bot 已启动，开始轮询 Telegram 消息...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()

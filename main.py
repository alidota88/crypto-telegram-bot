"""Entry point for the crypto Telegram bot."""

from __future__ import annotations

from bot import create_application
from bot.config import load_bot_token, setup_logging


def main() -> None:
    logger = setup_logging()
    token = load_bot_token()

    application = create_application(token, logger)

    logger.info("🤖 Bot 已启动，开始轮询 Telegram 消息...")
    application.run_polling()


if __name__ == "__main__":
    main()

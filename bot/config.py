"""Configuration helpers for the Telegram bot."""

from __future__ import annotations

import logging
import os

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_LEVEL = logging.INFO
ENV_TOKEN_KEY = "TELEGRAM_BOT_TOKEN"


def setup_logging() -> logging.Logger:
    """Configure logging and return the package logger."""
    logging.basicConfig(format=LOG_FORMAT, level=LOG_LEVEL)
    return logging.getLogger("crypto_bot")


def load_bot_token(env_var: str = ENV_TOKEN_KEY) -> str:
    """Read the bot token from the environment or raise an error."""
    token = os.getenv(env_var)
    if not token:
        raise RuntimeError(f"环境变量 {env_var} 没有设置！")
    return token

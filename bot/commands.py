"""Telegram command handlers."""

from __future__ import annotations

from typing import List

from telegram import Update
from telegram.ext import ContextTypes

from market_service import get_market_snapshot, get_price
from .subscriptions import SubscriptionRegistry


class CommandHandlers:
    """Container for bot command callbacks."""

    def __init__(
        self,
        price_subscriptions: SubscriptionRegistry,
        strategy_subscriptions: SubscriptionRegistry,
        logger,
    ) -> None:
        self._price_subscriptions = price_subscriptions
        self._strategy_subscriptions = strategy_subscriptions
        self._logger = logger

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        first_name = user.first_name or "朋友"
        text_lines: List[str] = [
            f"你好，{first_name}！",
            "我是你的 Crypto Assistant 机器人。",
            "",
            "基础命令：",
            "/price       - 查看 BTC 当前价格",
            "/market      - 查看 BTC & ETH 简要行情",
            "",
            "订阅相关：",
            "/sub_price      - 订阅定时行情推送",
            "/unsub_price    - 取消定时行情推送",
            "/sub_strategy   - 订阅策略筛选信号推送（实时开/平仓通知）",
            "/unsub_strategy - 取消策略信号推送",
        ]
        await update.message.reply_text("\n".join(text_lines))

    async def price(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            price_value = get_price("BTCUSDT")
            await update.message.reply_text(
                f"当前 BTC/USDT 价格约为：{price_value:.2f} USDT"
            )
        except Exception:  # pragma: no cover - network dependency
            self._logger.exception("获取 BTC 价格失败")
            await update.message.reply_text("获取 BTC 价格失败，请稍后再试。")

    async def market(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            snapshot = get_market_snapshot(["BTCUSDT", "ETHUSDT"])
            lines = ["[简要行情]"]
            for symbol, price_value in snapshot.items():
                lines.append(f"{symbol}: {price_value:.2f} USDT")
            await update.message.reply_text("\n".join(lines))
        except Exception:  # pragma: no cover - network dependency
            self._logger.exception("获取行情失败")
            await update.message.reply_text("获取行情失败，请稍后再试。")

    async def sub_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        self._price_subscriptions.add(chat_id)
        await update.message.reply_text("✅ 已订阅：定时行情推送（每 10 分钟一次）。")

    async def unsub_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        self._price_subscriptions.discard(chat_id)
        await update.message.reply_text("✅ 已取消：定时行情推送。")

    async def sub_strategy(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        self._strategy_subscriptions.add(chat_id)
        await update.message.reply_text("✅ 已订阅：策略筛选信号推送（有开仓/平仓就立刻提醒）。")

    async def unsub_strategy(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        self._strategy_subscriptions.discard(chat_id)
        await update.message.reply_text("✅ 已取消：策略信号推送。")

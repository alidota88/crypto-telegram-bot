"""Background job callbacks for the Telegram bot."""

from __future__ import annotations

from telegram.ext import Application, ContextTypes

from market_service import get_market_snapshot
from trading_engine import run_strategy_and_update_positions
from .subscriptions import SubscriptionRegistry


class JobHandlers:
    """Container for scheduled job callbacks."""

    def __init__(
        self,
        price_subscriptions: SubscriptionRegistry,
        strategy_subscriptions: SubscriptionRegistry,
        logger,
    ) -> None:
        self._price_subscriptions = price_subscriptions
        self._strategy_subscriptions = strategy_subscriptions
        self._logger = logger

    async def push_price(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._price_subscriptions:
            return
        try:
            snapshot = get_market_snapshot(["BTCUSDT", "ETHUSDT"])
        except Exception:  # pragma: no cover - network dependency
            self._logger.exception("定时行情推送失败")
            return

        lines = ["[定时行情推送]"]
        for symbol, price_value in snapshot.items():
            lines.append(f"{symbol}: {price_value:.2f} USDT")
        message = "\n".join(lines)

        for chat_id in self._price_subscriptions.snapshot():
            try:
                await context.application.bot.send_message(chat_id=chat_id, text=message)
            except Exception:  # pragma: no cover - network dependency
                self._logger.exception("发送行情推送失败 chat_id=%s", chat_id)

    async def push_strategy(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._strategy_subscriptions:
            return
        try:
            summary, trade_events = run_strategy_and_update_positions()
        except Exception:  # pragma: no cover - strategy failure
            self._logger.exception("策略任务失败")
            return

        if not trade_events:
            trade_events = [summary]

        for chat_id in self._strategy_subscriptions.snapshot():
            for message in trade_events:
                try:
                    await context.application.bot.send_message(chat_id=chat_id, text=message)
                except Exception:  # pragma: no cover - network dependency
                    self._logger.exception("发送策略推送失败 chat_id=%s", chat_id)


def register_jobs(application: Application, job_handlers: JobHandlers, logger) -> None:
    job_queue = application.job_queue
    if job_queue is None:
        logger.warning(  # pragma: no cover - runtime safeguard
            "JobQueue 未启用，定时推送功能不可用。请确认 requirements.txt 中安装的是 "
            "python-telegram-bot[job-queue]>=20.0"
        )
        return

    job_queue.run_repeating(
        job_handlers.push_price,
        interval=10 * 60,
        first=30,
        name="price_push",
    )
    job_queue.run_repeating(
        job_handlers.push_strategy,
        interval=60 * 60,
        first=60,
        name="strategy_push",
    )

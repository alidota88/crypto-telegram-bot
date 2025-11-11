"""Application factory for the Telegram bot."""

from __future__ import annotations

from telegram.ext import Application, CommandHandler

from .commands import CommandHandlers
from .jobs import JobHandlers, register_jobs
from .subscriptions import SubscriptionRegistry


def create_application(token: str, logger) -> Application:
    """Create and configure the Telegram application."""
    price_subscriptions = SubscriptionRegistry()
    strategy_subscriptions = SubscriptionRegistry()

    handlers = CommandHandlers(price_subscriptions, strategy_subscriptions, logger)
    job_handlers = JobHandlers(price_subscriptions, strategy_subscriptions, logger)

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("price", handlers.price))
    application.add_handler(CommandHandler("market", handlers.market))
    application.add_handler(CommandHandler("sub_price", handlers.sub_price))
    application.add_handler(CommandHandler("unsub_price", handlers.unsub_price))
    application.add_handler(CommandHandler("sub_strategy", handlers.sub_strategy))
    application.add_handler(CommandHandler("unsub_strategy", handlers.unsub_strategy))

    register_jobs(application, job_handlers, logger)

    return application

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .bot import commands
from .bot.handlers import include_routers
from .bot.jobs.unanswered_topics import update_unanswered_topics
from .bot.middlewares import register_middlewares
from .bot.utils.postgres.database import create_pool, init_db
from .config import load_config, Config
from .logger import setup_logger


async def on_shutdown(
    apscheduler: AsyncIOScheduler,
    dispatcher: Dispatcher,
    config: Config,
    bot: Bot,
) -> None:
    """
    Shutdown event handler. This runs when the bot shuts down.

    :param apscheduler: AsyncIOScheduler: The apscheduler instance.
    :param dispatcher: Dispatcher: The bot dispatcher.
    :param config: Config: The config instance.
    :param bot: Bot: The bot instance.
    """
    apscheduler.shutdown()
    await commands.delete(bot, config)
    await dispatcher.storage.close()
    await bot.delete_webhook()
    await bot.session.close()


async def on_startup(
    apscheduler: AsyncIOScheduler,
    config: Config,
    bot: Bot,
) -> None:
    """
    Startup event handler. This runs when the bot starts up.

    :param apscheduler: AsyncIOScheduler: The apscheduler instance.
    :param config: Config: The config instance.
    :param bot: Bot: The bot instance.
    """
    apscheduler.start()
    await commands.setup(bot, config)


async def main() -> None:
    """
    Main function that initializes the bot and starts the event loop.
    """
    config = load_config()

    # Initialize PostgreSQL pool
    pool = await create_pool(config.postgres.dsn())
    await init_db(pool)

    # Initialize apscheduler
    apscheduler = AsyncIOScheduler()

    # Initialize FSM storage (in-memory, ephemeral)
    storage = MemoryStorage()

    bot = Bot(
        token=config.bot.TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
        ),
    )
    dp = Dispatcher(
        apscheduler=apscheduler,
        storage=storage,
        config=config,
        bot=bot,
    )

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    include_routers(dp)
    register_middlewares(
        dp, config=config, pool=pool, apscheduler=apscheduler
    )

    # Scheduled job: update unanswered topics message every 5 minutes
    if config.bot.TOPICS_CHAT_ID:
        apscheduler.add_job(
            update_unanswered_topics,
            "interval",
            minutes=5,
            args=[bot, pool, config],
            next_run_time=datetime.now(),
        )

    await bot.delete_webhook()
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    setup_logger()
    asyncio.run(main())

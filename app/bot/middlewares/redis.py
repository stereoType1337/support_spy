from typing import Callable, Dict, Any, Awaitable

import asyncpg
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User, Chat

from app.bot.utils.postgres import PostgresStorage
from app.bot.utils.postgres.models import UserData
from app.bot.utils.postgres.stats import StatsStorage
from app.bot.utils.texts import SUPPORTED_LANGUAGES


class RedisMiddleware(BaseMiddleware):
    """
    Middleware for integrating PostgreSQL storage with Aiogram.

    Args:
        pool (asyncpg.Pool): The asyncpg connection pool.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any],
    ) -> Any:
        storage = PostgresStorage(self.pool)
        stats_storage = StatsStorage(self.pool)

        chat: Chat = data.get("event_chat")
        user: User = data.get("event_from_user")

        if chat.type == "private" and user is not None:
            user_db = await storage.get_user(user.id)
            user_data = user_db or UserData(
                message_thread_id=None,
                message_silent_id=None,
                message_silent_mode=False,
                is_banned=False,
                id=user.id,
                full_name=user.full_name,
                username=f"@{user.username}" if user.username else "-",
            )
            if user_db:
                user_data.full_name = user.full_name
                user_data.username = f"@{user.username}" if user.username else "-"

            if len(SUPPORTED_LANGUAGES.keys()) == 1:
                user_data.language_code = list(SUPPORTED_LANGUAGES.keys())[0]

            await storage.update_user(user.id, user_data)
        else:
            user_data = None

        data["redis"] = storage
        data["stats_storage"] = stats_storage
        data["user_data"] = user_data

        return await handler(event, data)

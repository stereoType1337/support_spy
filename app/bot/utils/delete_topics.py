"""
Utility functions for mass deletion of forum topics.
"""
import asyncio
from datetime import datetime
from typing import List, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter

from app.config import Config
from app.bot.utils.postgres import PostgresStorage
from app.bot.utils.postgres.stats import StatsStorage
from app.bot.utils.create_forum_topic import delete_forum_topic
import logging


def parse_date_range(date_range_str: str) -> Tuple[datetime, datetime] | None:
    """
    Парсит строку с диапазоном дат в формате "DD.MM.YYYY-DD.MM.YYYY" или "DD.MM.YYYY DD.MM.YYYY".

    :param date_range_str: Строка с диапазоном дат.
    :return: Кортеж (start_date, end_date) или None в случае ошибки.
    """
    try:
        if "-" in date_range_str:
            parts = date_range_str.split("-", 1)
        elif " " in date_range_str:
            parts = date_range_str.split(" ", 1)
        else:
            return None

        if len(parts) != 2:
            return None

        start_str = parts[0].strip()
        end_str = parts[1].strip()

        start_date = datetime.strptime(start_str, "%d.%m.%Y")
        end_date = datetime.strptime(end_str, "%d.%m.%Y")

        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)

        return start_date, end_date
    except ValueError:
        return None


def _parse_date(date_str: str) -> datetime | None:
    """Парсит строку даты в naive datetime (без таймзоны)."""
    # Берём первые 19 символов — "YYYY-MM-DD HH:MM:SS", отбрасываем таймзону
    try:
        return datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, IndexError):
        pass
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d")
    except (ValueError, IndexError):
        return None


async def get_topics_to_delete(
    redis: PostgresStorage,
    stats_storage: StatsStorage,
    start_date: datetime,
    end_date: datetime,
) -> List[int]:
    """
    Возвращает список user_id, чьи топики нужно удалить.
    Фильтрует по дате последней активности (topic_stats.updated_at).
    Для пользователей без topic_stats — по дате создания пользователя.

    :return: Список user_id для удаления.
    """
    all_users = await redis.get_all_users()
    all_topics = await stats_storage.get_all_topics()

    # Маппинг message_thread_id -> updated_at из topic_stats
    topic_last_activity = {}
    for topic in all_topics:
        dt = _parse_date(topic.updated_at)
        if dt:
            topic_last_activity[topic.message_thread_id] = dt

    users_to_delete = []
    for user in all_users:
        if user.message_thread_id is None:
            continue

        # Приоритет: дата последней активности из topic_stats
        last_activity = topic_last_activity.get(user.message_thread_id)

        # Фоллбэк: дата создания пользователя
        if last_activity is None:
            last_activity = _parse_date(user.created_at)

        if last_activity is None:
            continue

        if start_date <= last_activity <= end_date:
            users_to_delete.append(user.id)

    return users_to_delete


async def delete_topics_by_user_ids(
    bot: Bot,
    config: Config,
    redis: PostgresStorage,
    user_ids: List[int],
) -> Tuple[int, int, List[int]]:
    """
    Удаляет топики указанных пользователей.

    :return: Кортеж (успешно удалено, ошибок, список ID удалённых топиков).
    """
    deleted_count = 0
    error_count = 0
    deleted_thread_ids = []

    for user_id in user_ids:
        user = await redis.get_user(user_id)
        if not user or not user.message_thread_id:
            continue

        success = await delete_forum_topic(bot, config, user.message_thread_id)
        if success:
            deleted_count += 1
            deleted_thread_ids.append(user.message_thread_id)
            user.message_thread_id = None
            await redis.update_user(user.id, user)
        else:
            error_count += 1

        await asyncio.sleep(0.1)

    return deleted_count, error_count, deleted_thread_ids

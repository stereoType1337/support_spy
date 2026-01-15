"""
Utility functions for mass deletion of forum topics.
"""
import asyncio
from datetime import datetime
from typing import List, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter

from app.config import Config
from app.bot.utils.redis import RedisStorage
from app.bot.utils.redis.models import UserData
from app.bot.utils.create_forum_topic import delete_forum_topic
import logging


def parse_date_range(date_range_str: str) -> Tuple[datetime, datetime] | None:
    """
    Парсит строку с диапазоном дат в формате "DD.MM.YYYY-DD.MM.YYYY" или "DD.MM.YYYY DD.MM.YYYY".

    :param date_range_str: Строка с диапазоном дат.
    :return: Кортеж (start_date, end_date) или None в случае ошибки.
    """
    try:
        # Пробуем разные разделители
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

        # Парсим даты в формате DD.MM.YYYY
        start_date = datetime.strptime(start_str, "%d.%m.%Y")
        end_date = datetime.strptime(end_str, "%d.%m.%Y")

        # Устанавливаем время на начало и конец дня
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)

        return start_date, end_date
    except ValueError:
        return None


def is_user_in_date_range(user: UserData, start_date: datetime, end_date: datetime) -> bool:
    """
    Проверяет, попадает ли дата создания пользователя в указанный диапазон.

    :param user: Данные пользователя.
    :param start_date: Начальная дата.
    :param end_date: Конечная дата.
    :return: True, если дата создания пользователя попадает в диапазон.
    """
    try:
        # Парсим дату создания из UserData
        # Формат: "2025-09-08 08:04:43 MSK" или другой
        created_at_str = user.created_at

        # Пробуем разные форматы
        date_formats = [
            "%Y-%m-%d %H:%M:%S %Z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y",
        ]

        user_date = None
        for fmt in date_formats:
            try:
                user_date = datetime.strptime(created_at_str, fmt)
                break
            except ValueError:
                continue

        if user_date is None:
            # Если не удалось распарсить, пробуем взять первую часть до пробела
            try:
                user_date = datetime.strptime(created_at_str.split()[0], "%Y-%m-%d")
            except (ValueError, IndexError):
                return False

        # Проверяем, попадает ли дата в диапазон
        return start_date <= user_date <= end_date
    except Exception as e:
        logging.warning(f"Error checking date for user {user.id}: {e}")
        return False


async def delete_topics_by_date_range(
    bot: Bot,
    config: Config,
    redis: RedisStorage,
    start_date: datetime,
    end_date: datetime,
) -> Tuple[int, int, List[int]]:
    """
    Удаляет все топики пользователей, созданные в указанном диапазоне дат.

    :param bot: Экземпляр бота.
    :param config: Конфигурация.
    :param redis: Хранилище Redis.
    :param start_date: Начальная дата.
    :param end_date: Конечная дата.
    :return: Кортеж (успешно удалено, ошибок, список ID удаленных топиков).
    """
    # Получаем всех пользователей
    all_users = await redis.get_all_users()

    # Фильтруем пользователей по дате создания
    users_to_delete = [
        user for user in all_users
        if user.message_thread_id is not None
        and is_user_in_date_range(user, start_date, end_date)
    ]

    deleted_count = 0
    error_count = 0
    deleted_thread_ids = []

    # Удаляем топики
    for user in users_to_delete:
        if user.message_thread_id:
            success = await delete_forum_topic(bot, config, user.message_thread_id)
            if success:
                deleted_count += 1
                deleted_thread_ids.append(user.message_thread_id)
                # Обновляем данные пользователя - очищаем message_thread_id
                user.message_thread_id = None
                await redis.update_user(user.id, user)
            else:
                error_count += 1

            # Небольшая задержка, чтобы не превысить лимиты API
            await asyncio.sleep(0.1)

    return deleted_count, error_count, deleted_thread_ids


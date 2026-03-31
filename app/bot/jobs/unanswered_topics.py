from datetime import datetime, timezone, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from asyncpg import Pool

from app.bot.handlers.private.stats import format_unanswered_topics_message
from app.bot.utils.postgres.stats import StatsStorage
from app.config import Config

# ID сообщения, которое бот редактирует (хранится в памяти)
_pinned_message_id: int | None = None


async def update_unanswered_topics(bot: Bot, pool: Pool, config: Config) -> None:
    """Scheduled job: send or edit a message with unanswered topics."""
    global _pinned_message_id

    chat_id = config.bot.TOPICS_CHAT_ID
    thread_id = config.bot.TOPICS_THREAD_ID
    if not chat_id:
        return

    stats_storage = StatsStorage(pool)
    topics = await stats_storage.get_unanswered_topics_today()

    now = datetime.now(timezone(timedelta(hours=3)))
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    text = format_unanswered_topics_message(topics, date_str)
    if not text:
        text = f"📋 <b>Неотвеченные топики за {date_str}</b>\n\nВсе топики отвечены.\n\n<i>Обновлено в {time_str}</i>"

    # Пробуем отредактировать существующее сообщение
    if _pinned_message_id:
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=_pinned_message_id,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return
        except TelegramBadRequest:
            _pinned_message_id = None

    # Отправляем новое сообщение
    msg = await bot.send_message(
        chat_id=chat_id,
        message_thread_id=thread_id,
        text=text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    _pinned_message_id = msg.message_id

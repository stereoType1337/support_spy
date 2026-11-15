import asyncio
from typing import Optional
import re

from aiogram import Router, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import MagicData
from aiogram.types import Message

from app.bot.manager import Manager
from app.bot.types.album import Album
from app.bot.utils.postgres import PostgresStorage
from app.bot.utils.postgres.stats import StatsStorage
from app.bot.utils.create_forum_topic import edit_forum_topic_title
from app.bot.handlers.group.command import get_presets
from app.bot.utils.user_card import NO_PREVIEW, build_topic_keyboard, build_user_card

router = Router()
router.message.filter(
    MagicData(F.event_chat.id == F.config.bot.GROUP_ID),  # type: ignore
    F.chat.type.in_(["group", "supergroup"]),
    F.message_thread_id.is_not(None),
)



@router.message(F.forum_topic_created)
async def handler(message: Message, manager: Manager, redis: PostgresStorage) -> None:
    await asyncio.sleep(3)
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if not user_data:
        try:
            await message.delete()
        except Exception:
            pass
        return None  # noqa

    text, open_url = await build_user_card(manager, user_data)
    keyboard = build_topic_keyboard(open_url, await get_presets())

    sent_message = await message.bot.send_message(
        chat_id=manager.config.bot.GROUP_ID,
        text=text,
        message_thread_id=user_data.message_thread_id,
        reply_markup=keyboard,
        link_preview_options=NO_PREVIEW,
    )
    await sent_message.pin(disable_notification=True)


@router.message(F.pinned_message | F.forum_topic_edited | F.forum_topic_closed | F.forum_topic_reopened)
async def handler(message: Message) -> None:
    """
    Delete service messages such as pinned, edited, closed, or reopened forum topics.

    :param message: Message object.
    :return: None
    """
    await message.delete()


@router.message(F.media_group_id, F.from_user[F.is_bot.is_(False)])
@router.message(F.media_group_id.is_(None), F.from_user[F.is_bot.is_(False)])
async def handler(message: Message, manager: Manager, redis: PostgresStorage, stats_storage: StatsStorage, album: Optional[Album] = None) -> None:
    """
    Handles user messages and sends them to the respective user.
    If silent mode is enabled for the user, the messages are ignored.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: PostgresStorage object.
    :param album: Album object or None.
    :return: None
    """
    print(f"[DEBUG] Group handler: thread_id={message.message_thread_id}, from={message.from_user.id if message.from_user else None}")
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    print(f"[DEBUG] User data found: {user_data is not None}, user_id={user_data.id if user_data else None}")
    if not user_data: return None  # noqa

    if user_data.message_silent_mode:
        # If silent mode is enabled, ignore all messages.
        return

    text = None
    try:
        if not album:
            await message.copy_to(chat_id=user_data.id)
        else:
            await album.copy_to(chat_id=user_data.id)

        # Сообщение отправлено пользователю — меняем статус и название темы
        user_data.has_bot_replied = True
        user_data.has_sent_message = False
        await redis.update_user(user_data.id, user_data)

        # Записываем статистику ответа
        if message.message_thread_id:
            await stats_storage.record_response(
                message_thread_id=message.message_thread_id,
                responder_id=message.from_user.id,
                responder_name=message.from_user.full_name,
            )

        emoji = "🔑"
        full_name = clean_name(user_data.full_name) or "Пользователь"
        new_title = f"{full_name} {emoji}"
        print(f"[DEBUG] Переименовываем тему: {new_title}")
        if user_data.message_thread_id:
            try:
                await edit_forum_topic_title(message.bot, manager.config, user_data.message_thread_id, new_title)
            except Exception:
                pass
        text = manager.group_text.get("message_sent_to_user")

    except TelegramAPIError as ex:
        if "blocked" in ex.message:
            text = manager.group_text.get("blocked_by_user")
        else:
            text = manager.group_text.get("message_not_sent")

    except Exception:
        text = manager.group_text.get("message_not_sent")

    if text:
        msg = await message.reply(text)
        await asyncio.sleep(5)
        await msg.delete()


def clean_name(name):
    # Удаляем статусы-эмодзи (книжка, галка, часы, пробелы в конце)
    return re.sub(r'[\s📚✅⏰]+$', '', name or '')

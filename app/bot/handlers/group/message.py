import asyncio
from typing import Optional
import re

from aiogram import Router, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import MagicData
from aiogram.types import Message,InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.markdown import hlink
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.manager import Manager
from app.bot.types.album import Album
from app.bot.utils.postgres import PostgresStorage
from app.bot.utils.postgres.stats import StatsStorage
from app.bot.utils.create_forum_topic import edit_forum_topic_title
from app.bot.utils.api import get_user_info, get_user_keys, get_user_traffic, format_user_info_message
from app.bot.handlers.group.command import get_presets, ANS_CB_PREFIX

router = Router()
router.message.filter(
    MagicData(F.event_chat.id == F.config.bot.GROUP_ID),  # type: ignore
    F.chat.type.in_(["group", "supergroup"]),
    F.message_thread_id.is_not(None),
)


async def build_topic_keyboard(manager: Manager, user_id: int) -> InlineKeyboardMarkup:
    presets = await get_presets()

    bot_username = manager.config.api.BOT_USERNAME
    bot_link = f"https://t.me/{bot_username}?start=search_{user_id}"

    kb = InlineKeyboardBuilder()

    kb.row(
        InlineKeyboardButton(text="Открыть в боте", url=bot_link)
    )

    for key in sorted(presets.keys()):
        kb.button(text=key, callback_data=f"{ANS_CB_PREFIX}{key}")
    kb.adjust(1, 2)

    return kb.as_markup()


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

    user_info = await get_user_info(manager.config.api, user_data.id)
    text = ""

    if user_info:
        keys = await get_user_keys(manager.config.api, user_data.id)
        traffic_gb = await get_user_traffic(manager.config.remna, keys)
        text = format_user_info_message(user_info, keys, traffic_gb)
    else:
        url = f"https://t.me/{user_data.username[1:]}" if user_data.username != "-" else f"tg://user?id={user_data.id}"
        text = manager.text_message.get("user_started_bot")
        text = text.format(name=hlink(user_data.full_name, url), id=user_data.id)

    keyboard = await build_topic_keyboard(manager, user_data.id)

    sent_message = await message.bot.send_message(
        chat_id=manager.config.bot.GROUP_ID,
        text=text,
        message_thread_id=user_data.message_thread_id,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await sent_message.pin()


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
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
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
        text = manager.text_message.get("message_sent_to_user")

    except TelegramAPIError as ex:
        if "blocked" in ex.message:
            text = manager.text_message.get("blocked_by_user")
        else:
            text = manager.text_message.get("message_not_sent")

    except Exception:
        text = manager.text_message.get("message_not_sent")

    if text:
        msg = await message.reply(text)
        await asyncio.sleep(5)
        await msg.delete()


def clean_name(name):
    # Удаляем статусы-эмодзи (книжка, галка, часы, пробелы в конце)
    return re.sub(r'[\s📚✅⏰]+$', '', name or '')

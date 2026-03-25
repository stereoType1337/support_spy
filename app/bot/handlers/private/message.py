import asyncio

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.types import Message

from app.bot.manager import Manager
from app.bot.types.album import Album
from app.bot.utils.create_forum_topic import (
    create_forum_topic,
    get_or_create_forum_topic,
    edit_forum_topic_title,
)
from app.bot.utils.postgres import PostgresStorage
from app.bot.utils.postgres.models import UserData
from app.bot.utils.postgres.stats import StatsStorage

router = Router()
router.message.filter(F.chat.type == "private", StateFilter(None))


@router.edited_message()
async def handle_edited_message(message: Message, manager: Manager) -> None:
    """
    Handle edited messages.

    :param message: The edited message.
    :param manager: Manager object.
    :return: None
    """
    # Get the text for the edited message
    text = manager.text_message.get("message_edited")
    # Reply to the edited message with the specified text
    msg = await message.reply(text)
    # Wait for 5 seconds before deleting the reply
    await asyncio.sleep(5)
    # Delete the reply to the edited message
    await msg.delete()


@router.message(F.media_group_id)
@router.message(F.media_group_id.is_(None))
async def handle_incoming_message(
        message: Message,
        manager: Manager,
        redis: PostgresStorage,
        stats_storage: StatsStorage,
        user_data: UserData,
        album: Album | None = None,
) -> None:
    """
    Handles incoming messages and copies them to the forum topic.
    If the user is banned, the messages are ignored.

    :param message: The incoming message.
    :param manager: Manager object.
    :param redis: PostgresStorage object.
    :param user_data: UserData object.
    :param album: Album object or None.
    :return: None
    """
    # Check if the user is banned
    if user_data.is_banned:
        return

    async def copy_message_to_topic():
        """
        Copies the message or album to the forum topic.
        If no album is provided, the message is copied. Otherwise, the album is copied.
        """
        message_thread_id = await get_or_create_forum_topic(
            message.bot,
            redis,
            manager.config,
            user_data,
        )

        if not album:
            await message.forward(
                chat_id=manager.config.bot.GROUP_ID,
                message_thread_id=message_thread_id,
            )
        else:
            await album.copy_to(
                chat_id=manager.config.bot.GROUP_ID,
                message_thread_id=message_thread_id,
            )

    try:
        await copy_message_to_topic()
    except TelegramBadRequest as ex:
        error_message = ex.message.lower()
        if "message thread not found" in error_message or "topic_id_invalid" in error_message:
            user_data.message_thread_id = None
            user_data.message_thread_id = await create_forum_topic(
                message.bot,
                manager.config,
                user_data.full_name,
            )
            await redis.update_user(user_data.id, user_data)
            await copy_message_to_topic()
        else:
            raise

    # Record stats for this topic
    if user_data.message_thread_id:
        await stats_storage.create_or_update_topic(
            user_id=user_data.id,
            user_name=user_data.full_name,
            username=user_data.username,
            message_thread_id=user_data.message_thread_id,
            group_id=manager.config.bot.GROUP_ID,
        )

    # Send a confirmation message to the user
    text = manager.text_message.get("message_sent")
    # Reply to the edited message with the specified text
    msg = await message.reply(text)
    # Wait for 5 seconds before deleting the reply
    await asyncio.sleep(5)
    # Delete the reply to the edited message
    await msg.delete()

    # Update user status emoji in forum topic title
    if not user_data.is_bot_stopped and not user_data.is_bot_restarted:
        user_data.has_sent_message = True
        user_data.has_bot_replied = False
        await redis.update_user(user_data.id, user_data)
        emoji = "📚"
        new_title = f"{message.from_user.full_name} {emoji}"
        if user_data.message_thread_id:
            # Меняем только если эмодзи не стоит
            try:
                await edit_forum_topic_title(message.bot, manager.config, user_data.message_thread_id, new_title)
            except Exception as e:
                pass

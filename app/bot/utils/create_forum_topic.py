import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from app.config import Config
from .exceptions import CreateForumTopicException, NotEnoughRightsException, NotAForumException
from .postgres import PostgresStorage
from .postgres.models import UserData


async def get_or_create_forum_topic(
        bot: Bot,
        redis: PostgresStorage,
        config: Config,
        user_data: UserData,
) -> int:
    if user_data.message_thread_id is None:
        try:
            # If message_thread_id is not found, create a forum topic
            message_thread_id = await create_forum_topic(
                bot, config, user_data.full_name,
            )
            user_data.message_thread_id = message_thread_id
            await redis.update_user(user_data.id, user_data)

        except Exception as e:
            await bot.send_message(config.bot.DEV_ID, str(e))
            logging.exception(e)
    else:
        # Check if the topic still exists by trying to edit it (we'll restore the name if it exists)
        # We use a temporary name change to check existence, then restore if needed
        try:
            # Try to edit the topic with the same name to check if it exists
            # If topic doesn't exist, we'll get "message thread not found" error
            await bot.edit_forum_topic(
                chat_id=config.bot.GROUP_ID,
                message_thread_id=user_data.message_thread_id,
                name=user_data.full_name,
            )
        except TelegramBadRequest as ex:
            error_message = ex.message.lower()
            if "message thread not found" in error_message or "topic_id_invalid" in error_message:
                # Topic was deleted, clear message_thread_id and create a new one
                logging.warning(f"Topic {user_data.message_thread_id} not found or invalid, creating new one for user {user_data.id}")
                user_data.message_thread_id = None
                try:
                    message_thread_id = await create_forum_topic(
                        bot, config, user_data.full_name,
                    )
                    user_data.message_thread_id = message_thread_id
                    await redis.update_user(user_data.id, user_data)
                except Exception as e:
                    await bot.send_message(config.bot.DEV_ID, str(e))
                    logging.exception(e)
            elif "topic_not_modified" in error_message:
                # Topic exists but name is already the same - this is fine, topic exists
                pass
            else:
                # Other error, re-raise it
                raise

    return user_data.message_thread_id


async def create_forum_topic(bot: Bot, config: Config, name: str) -> int:
    """
    Creates a forum topic in the specified chat.

    :param bot: The Aiogram Bot instance.
    :param config: The configuration object.
    :param name: The name of the forum topic.

    :return: The message thread ID of the created forum topic.
    :raises NotEnoughRightsException: If the bot doesn't have enough rights to create a forum topic.
    :raises CreateForumTopicException: If an error occurs while creating the forum topic.
    """
    try:
        # Attempt to create a forum topic
        forum_topic = await bot.create_forum_topic(
            chat_id=config.bot.GROUP_ID,
            name=name,
            icon_custom_emoji_id=config.bot.BOT_EMOJI_ID,
            request_timeout=30,
        )
        return forum_topic.message_thread_id

    except TelegramRetryAfter as ex:
        # Handle Retry-After exception (rate limiting)
        logging.warning(ex.message)
        await asyncio.sleep(ex.retry_after)
        return await create_forum_topic(bot, config, name)

    except TelegramBadRequest as ex:
        if "not enough rights" in ex.message:
            # Raise an exception if the bot doesn't have enough rights
            raise NotEnoughRightsException

        elif "not a forum" in ex.message:
            # Raise an exception if the chat is not a forum
            raise NotAForumException

        # Raise a generic exception for other cases
        raise CreateForumTopicException

    except Exception as ex:
        # Re-raise any other exceptions
        raise ex


async def edit_forum_topic_title(bot: Bot, config: Config, message_thread_id: int, new_title: str) -> None:
    """
    Edits the title of a forum topic.

    :param bot: The Aiogram Bot instance.
    :param config: The configuration object.
    :param message_thread_id: The message thread ID of the forum topic.
    :param new_title: The new title for the forum topic.
    """
    await bot.edit_forum_topic(
        chat_id=config.bot.GROUP_ID,
        message_thread_id=message_thread_id,
        name=new_title,
    )


async def delete_forum_topic(bot: Bot, config: Config, message_thread_id: int) -> bool:
    """
    Deletes a forum topic.

    :param bot: The Aiogram Bot instance.
    :param config: The configuration object.
    :param message_thread_id: The message thread ID of the forum topic.
    :return: True if topic was deleted successfully, False otherwise.
    """
    try:
        await bot.delete_forum_topic(
            chat_id=config.bot.GROUP_ID,
            message_thread_id=message_thread_id,
        )
        return True
    except TelegramRetryAfter as ex:
        # Handle Retry-After exception (rate limiting)
        logging.warning(ex.message)
        await asyncio.sleep(ex.retry_after)
        return await delete_forum_topic(bot, config, message_thread_id)
    except TelegramBadRequest as ex:
        # Topic might not exist or bot doesn't have rights
        logging.warning(f"Failed to delete topic {message_thread_id}: {ex.message}")
        return False
    except Exception as ex:
        logging.exception(f"Error deleting topic {message_thread_id}: {ex}")
        return False

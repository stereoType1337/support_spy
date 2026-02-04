from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
)

from app.bot.utils.texts import SUPPORTED_LANGUAGES
from app.config import Config


async def setup(bot: Bot, config: Config) -> None:
    """
    Set up bot commands for various scopes and languages.

    :param bot: The Bot object.
    :param config: The Config object.
    """
    # Define bot commands for different languages
    commands = {
        "en": [
            BotCommand(command="start", description="Restart bot"),
            BotCommand(command="source", description="Source code"),
        ],
        "ru": [
            BotCommand(command="start", description="Перезапустить бота"),
            BotCommand(command="source", description="Исходники бота"),
        ]
    }

    if len(SUPPORTED_LANGUAGES) > 1:
        # If there are more than one supported language, add commands for changing the language
        commands["en"].append(
            BotCommand(command="language", description="Change language"),
        )
        commands["ru"].append(
            BotCommand(command="language", description="Изменить язык"),
        )

    group_commands = {
        "en": [
            BotCommand(command="help", description="Commands guide"),
            BotCommand(command="ans", description="Send preset"),
            BotCommand(command="add", description="Add preset"),
            BotCommand(command="del", description="Delete preset"),
            BotCommand(command="list", description="List presets"),
            BotCommand(command="show", description="Show preset"),
            BotCommand(command="ban", description="Block/Unblock user"),
            BotCommand(command="silent", description="Silent mode on/off"),
            BotCommand(command="information", description="User info"),
        ],
        "ru": [
            BotCommand(command="help", description="Справка по командам"),
            BotCommand(command="ans", description="Отправить пресет"),
            BotCommand(command="add", description="Добавить пресет"),
            BotCommand(command="del", description="Удалить пресет"),
            BotCommand(command="list", description="Список пресетов"),
            BotCommand(command="show", description="Показать пресет"),
            BotCommand(command="ban", description="Бан/разбан"),
            BotCommand(command="silent", description="Тихий режим"),
            BotCommand(command="information", description="Инфо о пользователе"),
        ]
    }

    # Commands for DEV_ID (with stats)
    dev_commands = {
        "en":
            commands["en"].copy() +
            [
                BotCommand(command="newsletter", description="Newsletter menu"),
                BotCommand(command="delete_topics", description="Delete topics by date range (DD.MM.YYYY-DD.MM.YYYY)"),
                BotCommand(command="stats", description="Support statistics"),
            ],
        "ru":
            commands["ru"].copy() +
            [
                BotCommand(command="newsletter", description="Меню рассылки"),
                BotCommand(command="delete_topics", description="Удалить топики за период (DD.MM.YYYY-DD.MM.YYYY)"),
                BotCommand(command="stats", description="Статистика поддержки"),
            ],
    }

    # Commands for ADMIN_IDS (without dev commands)
    admin_commands = {
        "en": commands["en"].copy(),
        "ru": commands["ru"].copy(),
    }

    try:
        # Set commands for dev
        await bot.set_my_commands(
            commands=dev_commands["en"],
            scope=BotCommandScopeChat(chat_id=config.bot.DEV_ID),
        )
        await bot.set_my_commands(
            commands=dev_commands["ru"],
            scope=BotCommandScopeChat(chat_id=config.bot.DEV_ID),
            language_code="ru",
        )
    except TelegramBadRequest:
        raise ValueError(f"Chat with DEV_ID {config.bot.DEV_ID} not found.")

    # Set commands for all admins from ADMIN_IDS
    for admin_id in config.bot.ADMIN_IDS:
        try:
            await bot.set_my_commands(
                commands=admin_commands["en"],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
            await bot.set_my_commands(
                commands=admin_commands["ru"],
                scope=BotCommandScopeChat(chat_id=admin_id),
                language_code="ru",
            )
        except TelegramBadRequest:
            pass  # Admin might not have started the bot yet

    # Set commands for all private chats in English language
    await bot.set_my_commands(
        commands=commands["en"],
        scope=BotCommandScopeAllPrivateChats(),
    )
    # Set commands for all private chats in Russian language
    await bot.set_my_commands(
        commands=commands["ru"],
        scope=BotCommandScopeAllPrivateChats(),
        language_code="ru",
    )
    # Set commands for all group chats in English language
    await bot.set_my_commands(
        commands=group_commands["en"],
        scope=BotCommandScopeAllGroupChats(),
    )
    # Set commands for all group chats in Russian language
    await bot.set_my_commands(
        commands=group_commands["ru"],
        scope=BotCommandScopeAllGroupChats(),
        language_code="ru"
    )


async def delete(bot: Bot, config: Config) -> None:
    """
    Delete bot commands for various scopes and languages.

    :param config: The Config object.
    :param bot: The Bot object.
    """

    try:
        # Delete commands for dev or admin in any language
        await bot.delete_my_commands(
            scope=BotCommandScopeChat(chat_id=config.bot.DEV_ID),
        )
        # Delete commands for dev or admin in Russian language
        await bot.delete_my_commands(
            scope=BotCommandScopeChat(chat_id=config.bot.DEV_ID),
            language_code="ru",
        )
    except TelegramBadRequest:
        raise ValueError(f"Chat with DEV_ID {config.bot.DEV_ID} not found.")

    # Delete commands for all private chats in any language
    await bot.delete_my_commands(
        scope=BotCommandScopeAllPrivateChats(),
    )
    # Delete commands for all private chats in Russian language
    await bot.delete_my_commands(
        scope=BotCommandScopeAllPrivateChats(),
        language_code="ru",
    )
    # Delete commands for all group chats in any language
    await bot.delete_my_commands(
        scope=BotCommandScopeAllGroupChats(),
    )
    # Delete commands for all group chats in Russian language
    await bot.delete_my_commands(
        scope=BotCommandScopeAllGroupChats(),
        language_code="ru",
    )

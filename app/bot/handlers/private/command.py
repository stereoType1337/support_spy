from aiogram import Router, F
from aiogram.filters import Command, MagicData
from aiogram.types import Message
from aiogram_newsletter.manager import ANManager

from app.bot.handlers.private.windows import Window
from app.bot.manager import Manager
from app.bot.utils.create_forum_topic import edit_forum_topic_title
from app.bot.utils.redis import RedisStorage
from app.bot.utils.redis.models import UserData
from app.bot.utils.delete_topics import parse_date_range, delete_topics_by_date_range

router = Router()
router.message.filter(F.chat.type == "private")


@router.message(Command("start"))
async def handler(
        message: Message,
        manager: Manager,
        redis: RedisStorage,
        user_data: UserData,
) -> None:
    """
    Handles the /start command.

    If the user has already selected a language, displays the main menu window.
    Otherwise, prompts the user to select a language.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: RedisStorage object.
    :param user_data: UserData object.
    :return: None
    """
    if user_data.language_code:
        await Window.main_menu(manager)
        await message.answer(manager.text_message.get("faq_msg"))
        user_data.has_bot_replied = True
        await redis.update_user(user_data.id, user_data)
        await manager.delete_message(message)
    else:
        await Window.select_language(manager)


@router.message(Command("language"))
async def handler(message: Message, manager: Manager, user_data: UserData) -> None:
    """
    Handles the /language command.

    If the user has already selected a language, prompts the user to select a new language.
    Otherwise, prompts the user to select a language.

    :param message: Message object.
    :param manager: Manager object.
    :param user_data: UserData object.
    :return: None
    """
    if user_data.language_code:
        await Window.change_language(manager)
    else:
        await Window.select_language(manager)
    await manager.delete_message(message)


@router.message(Command("source"))
async def handler(message: Message, manager: Manager) -> None:
    """
    Handles the /source command.

    :param message: Message object.
    :param manager: Manager object.
    :return: None
    """
    text = manager.text_message.get("source")
    await manager.send_message(text)
    await manager.delete_message(message)


@router.message(
    Command("newsletter"),
    MagicData(F.event_from_user.id == F.config.bot.DEV_ID),  # type: ignore
)
async def handler(
        message: Message,
        manager: Manager,
        an_manager: ANManager,
        redis: RedisStorage,
) -> None:
    """
    Handles the /newsletter command.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: RedisStorage object.
    :param an_manager: Manager object from aiogram_newsletter.
    :return: None
    """
    users_ids = await redis.get_all_users_ids()
    await an_manager.newsletter_menu(users_ids, Window.main_menu)
    await manager.delete_message(message)


@router.message(Command("reply"))
async def handle_bot_reply(message: Message, manager: Manager, redis: RedisStorage, user_data: UserData) -> None:
    """
    Handles bot replies to user messages.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: RedisStorage object.
    :param user_data: UserData object.
    :return: None
    """
    user_data.has_bot_replied = True
    await redis.update_user(user_data.id, user_data)
    emoji = "✅"
    new_title = f"{message.from_user.full_name} {emoji}"
    if user_data.message_thread_id:
        try:
            await edit_forum_topic_title(message.bot, manager.config, user_data.message_thread_id, new_title)
        except Exception as e:
            pass


@router.message(
    Command("delete_topics"),
    MagicData(F.event_from_user.id == F.config.bot.DEV_ID),  # type: ignore
)
async def handle_delete_topics(
    message: Message,
    manager: Manager,
    redis: RedisStorage,
) -> None:
    """
    Handles the /delete_topics command for mass deletion of forum topics.

    Usage: /delete_topics DD.MM.YYYY-DD.MM.YYYY
    Example: /delete_topics 01.12.2024-05.12.2024

    :param message: Message object.
    :param manager: Manager object.
    :param redis: RedisStorage object.
    :return: None
    """
    # Получаем аргументы команды
    command_text = message.text or ""
    parts = command_text.split(maxsplit=1)
    
    if len(parts) < 2:
        await message.answer(
            "❌ <b>Неверный формат команды</b>\n\n"
            "Использование: <code>/delete_topics DD.MM.YYYY-DD.MM.YYYY</code>\n\n"
            "Пример: <code>/delete_topics 01.12.2024-05.12.2024</code>",
            parse_mode="HTML"
        )
        await manager.delete_message(message)
        return

    date_range_str = parts[1]
    date_range = parse_date_range(date_range_str)

    if date_range is None:
        await message.answer(
            "❌ <b>Неверный формат дат</b>\n\n"
            "Используйте формат: <code>DD.MM.YYYY-DD.MM.YYYY</code>\n\n"
            "Пример: <code>01.12.2024-05.12.2024</code>",
            parse_mode="HTML"
        )
        await manager.delete_message(message)
        return

    start_date, end_date = date_range

    # Отправляем сообщение о начале процесса
    status_msg = await message.answer(
        f"⏳ <b>Начинаю удаление топиков...</b>\n\n"
        f"📅 Период: {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}\n"
        f"⏸ Пожалуйста, подождите...",
        parse_mode="HTML"
    )

    # Выполняем удаление
    deleted_count, error_count, deleted_thread_ids = await delete_topics_by_date_range(
        message.bot,
        manager.config,
        redis,
        start_date,
        end_date,
    )

    # Формируем результат
    result_text = (
        f"✅ <b>Удаление завершено</b>\n\n"
        f"📅 Период: {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}\n"
        f"✅ Успешно удалено: <b>{deleted_count}</b> топиков\n"
    )
    
    if error_count > 0:
        result_text += f"❌ Ошибок: <b>{error_count}</b>\n"

    await status_msg.edit_text(result_text, parse_mode="HTML")
    await manager.delete_message(message)

from aiogram import Router, F
from aiogram.filters import Command, MagicData
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram_newsletter.manager import ANManager

from app.bot.handlers.private.windows import Window
from app.bot.manager import Manager
from app.bot.utils.create_forum_topic import edit_forum_topic_title
from app.bot.utils.postgres import PostgresStorage
from app.bot.utils.postgres.stats import StatsStorage
from app.bot.utils.postgres.models import UserData
from app.bot.utils.delete_topics import parse_date_range, get_topics_to_delete, delete_topics_by_user_ids

router = Router()
router.message.filter(F.chat.type == "private")

# Отдельный роутер для dev-команд, работающих в любых чатах (private + group)
router_dev = Router()


@router.message(Command("start"))
async def handler(
        message: Message,
        manager: Manager,
        redis: PostgresStorage,
        user_data: UserData,
) -> None:
    """
    Handles the /start command.

    If the user has already selected a language, displays the main menu window.
    Otherwise, prompts the user to select a language.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: PostgresStorage object.
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


@router.message(
    Command("newsletter"),
    MagicData(F.event_from_user.id.in_(F.config.bot.DEV_IDS)),  # type: ignore
)
async def handler(
        message: Message,
        manager: Manager,
        an_manager: ANManager,
        redis: PostgresStorage,
) -> None:
    """
    Handles the /newsletter command.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: PostgresStorage object.
    :param an_manager: Manager object from aiogram_newsletter.
    :return: None
    """
    users_ids = await redis.get_all_users_ids()
    await an_manager.newsletter_menu(users_ids, Window.main_menu)
    await manager.delete_message(message)


@router.message(Command("reply"))
async def handle_bot_reply(message: Message, manager: Manager, redis: PostgresStorage, user_data: UserData) -> None:
    """
    Handles bot replies to user messages.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: PostgresStorage object.
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


DELETE_CONFIRM_PREFIX = "del_topics_confirm:"
DELETE_CANCEL_CB = "del_topics_cancel"

# Временное хранилище для pending удалений {user_id: {"user_ids": [...], "start": str, "end": str}}
_pending_deletions: dict = {}


@router_dev.message(
    Command("delete_topics"),
    MagicData(F.event_from_user.id.in_(F.config.bot.DEV_IDS)),  # type: ignore
)
async def handle_delete_topics(
    message: Message,
    manager: Manager,
    redis: PostgresStorage,
    stats_storage: StatsStorage,
) -> None:
    """
    Handles the /delete_topics command for mass deletion of forum topics.

    Usage: /delete_topics DD.MM.YYYY-DD.MM.YYYY
    Example: /delete_topics 01.12.2024-05.12.2024
    Filters by last activity date (topic_stats.updated_at), not by creation date.
    """
    command_text = message.text or ""
    parts = command_text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            "❌ <b>Неверный формат команды</b>\n\n"
            "Использование: <code>/delete_topics DD.MM.YYYY-DD.MM.YYYY</code>\n\n"
            "Пример: <code>/delete_topics 01.12.2024-05.12.2024</code>\n\n"
            "Фильтрует по дате последнего сообщения в топике.",
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

    status_msg = await message.answer(
        f"⏳ <b>Подсчитываю топики...</b>\n\n"
        f"📅 Период: {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}",
        parse_mode="HTML"
    )

    user_ids = await get_topics_to_delete(redis, stats_storage, start_date, end_date)

    if not user_ids:
        await status_msg.edit_text(
            f"📅 Период: {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}\n\n"
            f"Топиков для удаления не найдено.",
            parse_mode="HTML"
        )
        await manager.delete_message(message)
        return

    # Сохраняем данные для подтверждения
    _pending_deletions[message.from_user.id] = {
        "user_ids": user_ids,
        "start": start_date.strftime('%d.%m.%Y'),
        "end": end_date.strftime('%d.%m.%Y'),
    }

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text=f"Удалить {len(user_ids)} топиков",
            callback_data=f"{DELETE_CONFIRM_PREFIX}{message.from_user.id}",
        ),
        InlineKeyboardButton(text="Отмена", callback_data=DELETE_CANCEL_CB),
    )

    await status_msg.edit_text(
        f"📅 Период: {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}\n"
        f"🗑 Будет удалено: <b>{len(user_ids)}</b> топиков\n\n"
        f"Фильтр: по дате последней активности в топике.\n\n"
        f"Подтвердите удаление:",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    await manager.delete_message(message)


@router_dev.callback_query(F.data == DELETE_CANCEL_CB)
async def handle_delete_cancel(callback: CallbackQuery) -> None:
    _pending_deletions.pop(callback.from_user.id, None)
    await callback.message.edit_text("❌ Удаление отменено.", parse_mode="HTML")
    await callback.answer()


@router_dev.callback_query(F.data.startswith(DELETE_CONFIRM_PREFIX))
async def handle_delete_confirm(
    callback: CallbackQuery,
    manager: Manager,
    redis: PostgresStorage,
) -> None:
    pending = _pending_deletions.pop(callback.from_user.id, None)
    if not pending:
        await callback.message.edit_text("❌ Данные устарели. Повторите команду.", parse_mode="HTML")
        await callback.answer()
        return

    user_ids = pending["user_ids"]
    start_str = pending["start"]
    end_str = pending["end"]

    await callback.message.edit_text(
        f"⏳ <b>Удаляю {len(user_ids)} топиков...</b>\n\n"
        f"📅 Период: {start_str} - {end_str}\n"
        f"⏸ Пожалуйста, подождите...",
        parse_mode="HTML"
    )
    await callback.answer()

    deleted_count, error_count, _ = await delete_topics_by_user_ids(
        callback.bot,
        manager.config,
        redis,
        user_ids,
    )

    result_text = (
        f"✅ <b>Удаление завершено</b>\n\n"
        f"📅 Период: {start_str} - {end_str}\n"
        f"✅ Успешно удалено: <b>{deleted_count}</b> топиков\n"
    )

    if error_count > 0:
        result_text += f"❌ Ошибок: <b>{error_count}</b>\n"

    await callback.message.edit_text(result_text, parse_mode="HTML")

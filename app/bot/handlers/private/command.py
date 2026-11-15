import asyncio
from contextlib import suppress

from aiogram import Bot, Router, F
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandObject, MagicData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

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


START_BOT_PREFIX = "bot_"


@router.message(Command("start"))
async def handler(
        message: Message,
        command: CommandObject,
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
    args = command.args or ""
    if args.startswith(START_BOT_PREFIX) and args.removeprefix(START_BOT_PREFIX).isdigit():
        user_data.source_bot_id = int(args.removeprefix(START_BOT_PREFIX))
        await redis.update_user(user_data.id, user_data)

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


class NewsletterFSM(StatesGroup):
    waiting_target = State()
    waiting_message = State()
    confirming = State()


NL_TARGET_PREFIX = "nl_target:"
NL_CONFIRM_CB = "nl_confirm"
NL_CANCEL_CB = "nl_cancel"


@router.message(
    Command("newsletter"),
    MagicData(F.event_from_user.id.in_(F.config.bot.DEV_IDS)),  # type: ignore
)
async def handler_newsletter(
        message: Message,
        manager: Manager,
        state: FSMContext,
) -> None:
    """Шаг 1: предложить выбор аудитории."""
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="Всем", callback_data=f"{NL_TARGET_PREFIX}all"),
        InlineKeyboardButton(text="Без ответа", callback_data=f"{NL_TARGET_PREFIX}unanswered"),
    )
    kb.row(InlineKeyboardButton(text="Отмена", callback_data=NL_CANCEL_CB))

    await state.set_state(NewsletterFSM.waiting_target)
    await message.answer(
        "📨 <b>Кому отправить рассылку?</b>",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    await manager.delete_message(message)


@router.callback_query(F.data == NL_CANCEL_CB)
async def newsletter_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    with suppress(Exception):
        await callback.message.edit_text("❌ Рассылка отменена.")
    await callback.answer()


@router.callback_query(
    F.data.startswith(NL_TARGET_PREFIX),
    NewsletterFSM.waiting_target,
)
async def newsletter_pick_target(
        callback: CallbackQuery,
        state: FSMContext,
        redis: PostgresStorage,
) -> None:
    """Шаг 2: подгрузить список и попросить сообщение."""
    target = callback.data.removeprefix(NL_TARGET_PREFIX)
    if target == "all":
        user_ids = await redis.get_all_users_ids()
        target_label = "всем"
    elif target == "unanswered":
        user_ids = await redis.get_unanswered_user_ids()
        target_label = "тем, кому не ответили"
    else:
        await callback.answer("Unknown target", show_alert=True)
        return

    if not user_ids:
        await state.clear()
        with suppress(Exception):
            await callback.message.edit_text("⚠️ Получателей не найдено.")
        await callback.answer()
        return

    await state.update_data(user_ids=user_ids, target_label=target_label)
    await state.set_state(NewsletterFSM.waiting_message)

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="Отмена", callback_data=NL_CANCEL_CB))
    with suppress(Exception):
        await callback.message.edit_text(
            f"📨 Цель: <b>{target_label}</b>\n"
            f"Получателей: <b>{len(user_ids)}</b>\n\n"
            "Отправь сюда сообщение для рассылки (текст / фото / видео — любое).",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )
    await callback.answer()


@router.message(NewsletterFSM.waiting_message)
async def newsletter_capture(
        message: Message,
        state: FSMContext,
) -> None:
    """Шаг 3: сохранить ссылку на сообщение и показать превью с подтверждением."""
    state_data = await state.get_data()
    user_ids = state_data.get("user_ids", [])
    target_label = state_data.get("target_label", "?")

    await state.update_data(
        source_chat_id=message.chat.id,
        source_message_id=message.message_id,
    )
    await state.set_state(NewsletterFSM.confirming)

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ Отправить", callback_data=NL_CONFIRM_CB),
        InlineKeyboardButton(text="❌ Отмена", callback_data=NL_CANCEL_CB),
    )

    await message.reply(
        f"📨 Рассылка <b>{target_label}</b> — {len(user_ids)} получателей.\n\n"
        "Отправить сообщение выше?",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data == NL_CONFIRM_CB, NewsletterFSM.confirming)
async def newsletter_confirm(
        callback: CallbackQuery,
        state: FSMContext,
) -> None:
    """Шаг 4: запустить фоновую рассылку и обновлять статус-сообщение."""
    state_data = await state.get_data()
    user_ids: list[int] = list(state_data.get("user_ids", []))
    source_chat_id: int = state_data.get("source_chat_id")
    source_message_id: int = state_data.get("source_message_id")
    await state.clear()

    with suppress(Exception):
        await callback.message.edit_text(
            f"⏳ Запускаю рассылку на {len(user_ids)} получателей…"
        )
    await callback.answer()

    asyncio.create_task(
        _run_broadcast(
            bot=callback.bot,
            admin_id=callback.from_user.id,
            status_message_id=callback.message.message_id,
            user_ids=user_ids,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
        )
    )


async def _run_broadcast(
        bot: Bot,
        admin_id: int,
        status_message_id: int,
        user_ids: list[int],
        source_chat_id: int,
        source_message_id: int,
) -> None:
    total = len(user_ids)
    sent = 0
    failed = 0
    loop = asyncio.get_running_loop()
    last_progress = 0.0

    async def _send(uid: int) -> bool:
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=source_chat_id,
                message_id=source_message_id,
            )
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.copy_message(
                    chat_id=uid,
                    from_chat_id=source_chat_id,
                    message_id=source_message_id,
                )
                return True
            except Exception:
                return False
        except Exception:
            return False

    for i, uid in enumerate(user_ids, 1):
        if await _send(uid):
            sent += 1
        else:
            failed += 1
        # ~25 msg/sec — под глобальным лимитом Telegram (30/sec).
        await asyncio.sleep(0.04)

        now = loop.time()
        if now - last_progress >= 5:
            with suppress(Exception):
                await bot.edit_message_text(
                    chat_id=admin_id,
                    message_id=status_message_id,
                    text=(
                        f"⏳ Рассылка: {i}/{total}\n"
                        f"✅ Успешно: {sent}\n"
                        f"❌ Ошибок: {failed}"
                    ),
                )
            last_progress = now

    with suppress(Exception):
        await bot.edit_message_text(
            chat_id=admin_id,
            message_id=status_message_id,
            text=(
                f"✅ <b>Рассылка завершена</b>\n\n"
                f"Всего: <b>{total}</b>\n"
                f"Успешно: <b>{sent}</b>\n"
                f"Ошибок: <b>{failed}</b>"
            ),
            parse_mode="HTML",
        )


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

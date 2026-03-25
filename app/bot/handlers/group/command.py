import asyncio
import json
import re
from contextlib import suppress
from pathlib import Path
from typing import Any

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from aiogram.filters import Command, MagicData
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from aiogram.utils.markdown import hcode, hbold, hlink
from aiogram.utils.text_decorations import html_decoration as hd

from app.bot.manager import Manager
from app.bot.utils.api import get_user_info, get_user_keys, get_user_traffic, format_user_info_message
from app.bot.utils.postgres import PostgresStorage
from app.bot.utils.postgres.stats import StatsStorage
from app.bot.utils.create_forum_topic import edit_forum_topic_title

router_id = Router()
router_id.message.filter(
    F.chat.type.in_(["group", "supergroup"]),
)


def _is_admin(message: Message, manager: Manager) -> bool:
    if not message.from_user:
        return False
    return (
        message.from_user.id in manager.config.bot.DEV_IDS
        or message.from_user.id in manager.config.bot.ADMIN_IDS
    )



@router_id.message(Command("id"))
async def handler(message: Message) -> None:
    """
    Sends chat ID in response to the /id command.
    """
    await message.reply(hcode(message.chat.id))


router = Router()
router.message.filter(
    F.message_thread_id.is_not(None),
    F.chat.type.in_(["group", "supergroup"]),
    MagicData(F.event_chat.id == F.config.bot.GROUP_ID),  # type: ignore
)

ANS_CB_PREFIX = "ans:"
PRESETS_FILE = Path(__file__).with_name("ans_presets.json")
_PRESETS_LOCK = asyncio.Lock()
_PRESETS_CACHE: dict[str, str | dict] | None = None


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace(" ", "_")


async def _load_presets_from_disk() -> dict[str, str | dict]:
    """
    Reads presets JSON from disk. If file doesn't exist, creates an empty one.
    Supports both string values and dict values with text/photo_file_id.
    """
    if not PRESETS_FILE.exists():
        PRESETS_FILE.write_text("{}", encoding="utf-8")

    raw = PRESETS_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return {}

    data: Any = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("ans_presets.json must contain a JSON object (dict)")

    out: dict[str, str | dict] = {}
    for k, v in data.items():
        if not isinstance(k, str):
            continue
        nk = _normalize_key(k)
        if not nk:
            continue
        if isinstance(v, str):
            out[nk] = v
        elif isinstance(v, dict) and ("text" in v or "photo_file_id" in v):
            out[nk] = v
    return out


async def get_presets() -> dict[str, str | dict]:
    """
    Cached presets read; reloadable.
    """
    global _PRESETS_CACHE
    async with _PRESETS_LOCK:
        if _PRESETS_CACHE is None:
            _PRESETS_CACHE = await _load_presets_from_disk()
        return dict(_PRESETS_CACHE)


async def reload_presets() -> dict[str, str | dict]:
    global _PRESETS_CACHE
    async with _PRESETS_LOCK:
        _PRESETS_CACHE = await _load_presets_from_disk()
        return dict(_PRESETS_CACHE)


async def save_presets(presets: dict[str, str | dict]) -> None:
    """
    Atomic-ish save to disk (write temp then replace).
    """
    tmp = PRESETS_FILE.with_suffix(".json.tmp")
    payload = json.dumps(presets, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.write_text(payload + "\n", encoding="utf-8")
    tmp.replace(PRESETS_FILE)


def _clean_name(name: str) -> str:
    return re.sub(r'[\s📚✅⏰🔑]+$', '', name or '')


def build_ans_keyboard(presets: dict[str, str | dict]) -> InlineKeyboardBuilder:
    """
    Builds inline keyboard from presets keys.
    """
    kb = InlineKeyboardBuilder()

    for key in sorted(presets.keys()):
        # callback_data — только технич. строка, HTML не нужен
        kb.button(text=key, callback_data=f"{ANS_CB_PREFIX}{key}")

    kb.adjust(2)
    return kb


@router.message(Command("help"))
async def help_command(message: Message, manager: Manager) -> None:
    """/help — справка по командам."""
    if not _is_admin(message, manager):
        await message.reply("⛔️ Недостаточно прав.")
        return

    text = """<b>📚 Справка по командам</b>

<b>Пресеты (быстрые ответы):</b>
• /ans — показать кнопки с пресетами
• /add [key] [текст] — добавить текстовый пресет
• /add [key] (ответом на фото) — добавить фото-пресет
• /add [key] (ответом на сообщение) — взять текст из сообщения
• /del [key] — удалить пресет
• /list — список всех пресетов
• /show [key] — показать содержимое пресета

<b>Управление пользователем:</b>
• /ban — заблокировать/разблокировать
• /silent — включить/выключить тихий режим
• /information — информация о пользователе

<b>Примеры добавления пресетов:</b>
<code>/add привет Здравствуйте! Чем могу помочь?</code>
<code>/add инструкция</code> (ответом на сообщение с текстом)
<code>/add скрин</code> (ответом на фото)

<b>Советы:</b>
• Ключ пресета автоматически приводится к нижнему регистру
• Пробелы в ключе заменяются на _
• Для перезагрузки пресетов из файла: /edit reload"""

    await message.reply(text, parse_mode="HTML")


@router.message(Command("ans"))
async def ans_command(message: Message, redis: PostgresStorage) -> None:
    """
    /ans — creates a message with inline buttons (preset answers) in current support topic.
    """
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if not user_data:
        return

    presets = await get_presets()
    if not presets:
        await message.reply("Пресеты пустые. Добавь через /edit add [key] [text] или отредачь ans_presets.json.")
        return

    kb = build_ans_keyboard(presets)
    await message.reply("Выбери пресет ответа:", reply_markup=kb.as_markup())


@router.callback_query(
    F.data.startswith(ANS_CB_PREFIX),
    MagicData(F.event_chat.id == F.config.bot.GROUP_ID),  # type: ignore
)
async def ans_callback(callback: CallbackQuery, manager: Manager, redis: PostgresStorage, stats_storage: StatsStorage) -> None:
    """
    On preset button click: sends preset text to user напрямую, и подтверждает в топике.
    """
    if not callback.message or callback.message.message_thread_id is None:
        await callback.answer("Это можно использовать только в топиках.", show_alert=True)
        return

    preset_key = callback.data.split(":", 1)[1] if callback.data else ""
    preset_key = _normalize_key(preset_key)

    presets = await get_presets()
    preset_value = presets.get(preset_key)
    if not preset_value:
        await callback.answer("Пресет не найден (возможно обновили файл). Нажми /ans заново.", show_alert=True)
        return

    # Определяем текст и photo_file_id из пресета
    if isinstance(preset_value, dict):
        preset_text = preset_value.get("text", "")
        photo_file_id = preset_value.get("photo_file_id")
    else:
        preset_text = preset_value
        photo_file_id = None

    user_data = await redis.get_by_message_thread_id(callback.message.message_thread_id)
    if not user_data:
        await callback.answer("Не нашёл пользователя для этого топика.", show_alert=True)
        return

    if user_data.message_silent_mode:
        await callback.answer("У пользователя включён silent mode.", show_alert=True)
        return

    with suppress(TelegramBadRequest):
        await callback.answer("Отправляю…")

    ok = True
    error_text: str | None = None

    try:
        if photo_file_id:
            await callback.bot.send_photo(
                chat_id=user_data.id,
                photo=photo_file_id,
                caption=preset_text or None,
            )
        else:
            await callback.bot.send_message(chat_id=user_data.id, text=preset_text)
    except TelegramAPIError as ex:
        ok = False
        if "blocked" in (ex.message or ""):
            error_text = manager.text_message.get("blocked_by_user")
        else:
            error_text = manager.text_message.get("message_not_sent")
    except Exception:
        ok = False
        error_text = manager.text_message.get("message_not_sent")

    if ok:
        # Обновляем статус диалога
        user_data.has_bot_replied = True
        user_data.has_sent_message = False
        await redis.update_user(user_data.id, user_data)

        # Засчитываем ответ админу в статистику
        if callback.message.message_thread_id and callback.from_user:
            await stats_storage.record_response(
                message_thread_id=callback.message.message_thread_id,
                responder_id=callback.from_user.id,
                responder_name=callback.from_user.full_name,
            )

        # Переименовываем тему (эмодзи 🔑)
        full_name = _clean_name(user_data.full_name) or "Пользователь"
        new_title = f"{full_name} 🔑"
        print(f"[DEBUG] Переименовываем тему (пресет): {new_title}")
        if user_data.message_thread_id:
            try:
                await edit_forum_topic_title(callback.bot, manager.config, user_data.message_thread_id, new_title)
            except Exception:
                pass

    # Подтверждение в топике
    if ok:
        display_text = f"[Фото] {preset_text}" if photo_file_id and preset_text else "[Фото]" if photo_file_id else preset_text
        confirm = f"✅ Отправлено пользователю пресетом:\n{hd.quote(display_text)}"
    else:
        confirm = f"❌ Не удалось отправить: {hd.quote(error_text or 'ошибка')}"

    with suppress(TelegramBadRequest):
        await callback.message.reply(confirm)


async def _add_preset(message: Message, manager: Manager, key: str, extra_text: str | None = None) -> None:
    """Универсальная функция добавления пресета."""
    global _PRESETS_CACHE

    key = _normalize_key(key)
    if not key:
        await message.reply("Ключ пустой/некорректный.")
        return

    reply = message.reply_to_message
    value: str | dict | None = None
    label: str = ""

    # 1. Ответ на фото
    if reply and reply.photo:
        file_id = reply.photo[-1].file_id
        caption = reply.caption or extra_text or ""
        value = {"text": caption, "photo_file_id": file_id}
        label = f"[Фото] {caption}" if caption else "[Фото]"

    # 2. Ответ на текстовое сообщение
    elif reply and reply.text:
        value = reply.text
        label = value[:50] + "..." if len(value) > 50 else value

    # 3. Текст в самой команде
    elif extra_text:
        value = extra_text
        label = value[:50] + "..." if len(value) > 50 else value

    if not value:
        await message.reply(
            "Использование:\n"
            "• /add [key] [text] — текст в команде\n"
            "• /add [key] (ответом на сообщение) — текст из ответа\n"
            "• /add [key] (ответом на фото) — фото с подписью"
        )
        return

    async with _PRESETS_LOCK:
        if _PRESETS_CACHE is None:
            _PRESETS_CACHE = await _load_presets_from_disk()
        _PRESETS_CACHE[key] = value
        await save_presets(_PRESETS_CACHE)

    await message.reply(f"✅ Сохранил пресет: {hbold(hd.quote(key))}\n{hd.quote(label)}")


@router.message(Command("add"))
async def add_preset_command(message: Message, manager: Manager) -> None:
    """
    /add [key] [text] — добавить пресет.
    Можно использовать ответом на сообщение/фото.
    """
    if not _is_admin(message, manager):
        await message.reply("⛔️ Недостаточно прав.")
        return

    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await message.reply(
            "Использование:\n"
            "• /add [key] [text]\n"
            "• /add [key] (ответом на сообщение/фото)"
        )
        return

    key = parts[1]
    extra_text = parts[2].strip() if len(parts) > 2 else None
    await _add_preset(message, manager, key, extra_text)


@router.message(Command("del"))
async def del_preset_command(message: Message, manager: Manager) -> None:
    """/del [key] — удалить пресет."""
    global _PRESETS_CACHE

    if not _is_admin(message, manager):
        await message.reply("⛔️ Недостаточно прав.")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Использование: /del [key]")
        return

    key = _normalize_key(parts[1])

    async with _PRESETS_LOCK:
        if _PRESETS_CACHE is None:
            _PRESETS_CACHE = await _load_presets_from_disk()

        if key not in _PRESETS_CACHE:
            await message.reply("Такого пресета нет.")
            return

        _PRESETS_CACHE.pop(key, None)
        await save_presets(_PRESETS_CACHE)

    await message.reply(f"✅ Удалил пресет: {hbold(hd.quote(key))}")


@router.message(Command("list"))
async def list_presets_command(message: Message, manager: Manager) -> None:
    """/list — показать все пресеты."""
    if not _is_admin(message, manager):
        await message.reply("⛔️ Недостаточно прав.")
        return

    presets = await get_presets()
    if not presets:
        await message.reply("Пресетов нет. Добавь через /add [key] [text].")
        return

    keys = "\n".join(f"• {hd.quote(k)}" for k in sorted(presets.keys()))
    await message.reply(f"Пресеты ({len(presets)}):\n{keys}")


@router.message(Command("show"))
async def show_preset_command(message: Message, manager: Manager) -> None:
    """/show [key] — показать содержимое пресета."""
    if not _is_admin(message, manager):
        await message.reply("⛔️ Недостаточно прав.")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Использование: /show [key]")
        return

    key = _normalize_key(parts[1])
    presets = await get_presets()
    value = presets.get(key)

    if not value:
        await message.reply("Пресет не найден.")
        return

    if isinstance(value, dict):
        text = value.get("text", "")
        photo_id = value.get("photo_file_id")
        if photo_id:
            await message.reply_photo(photo=photo_id, caption=f"{hbold(hd.quote(key))}:\n{text or '[без текста]'}")
        else:
            await message.reply(f"{hbold(hd.quote(key))}:\n{hd.quote(text)}")
    else:
        await message.reply(f"{hbold(hd.quote(key))}:\n{hd.quote(value)}")


@router.message(Command("edit"))
async def edit_presets(message: Message, manager: Manager) -> None:
    """
    /edit — manage presets stored in ans_presets.json

    Commands:
      /edit list
      /edit show [key]
      /edit add [key] [text] (или ответом на сообщение)
      /edit del [key]
      /edit reload
    """
    global _PRESETS_CACHE

    if not _is_admin(message, manager):
        await message.reply("⛔️ Недостаточно прав.")
        return

    parts = (message.text or "").split(maxsplit=3)
    action = parts[1].lower() if len(parts) > 1 else "list"

    if action in {"help", "h", "?"}:
        await message.reply(
            "Управление пресетами:\n"
            "• /edit list — список пресетов\n"
            "• /edit show [key] — показать пресет\n"
            "• /edit del [key] — удалить пресет\n"
            "• /edit reload — перечитать файл\n\n"
            "Добавление пресетов:\n"
            "• /add [key] [text]\n"
            "• /add [key] (ответом на сообщение/фото)"
        )
        return

    if action == "reload":
        try:
            presets = await reload_presets()
        except Exception as e:
            await message.reply(f"❌ Не удалось перечитать файл: {hd.quote(str(e))}")
            return
        await message.reply(f"✅ Перечитал файл. Пресетов: {len(presets)}")
        return

    if action in {"list", "ls"}:
        presets = await get_presets()
        if not presets:
            await message.reply("Пресетов нет. Добавь через /add [key] [text].")
            return
        keys = "\n".join(f"• {hd.quote(k)}" for k in sorted(presets.keys()))
        await message.reply(f"Пресеты ({len(presets)}):\n{keys}")
        return

    if action == "show":
        if len(parts) < 3:
            await message.reply("Использование: /edit show [key]")
            return
        key = _normalize_key(parts[2])
        presets = await get_presets()
        value = presets.get(key)
        if not value:
            await message.reply("Не найдено.")
            return
        if isinstance(value, dict):
            text = value.get("text", "")
            has_photo = "photo_file_id" in value
            display = f"[Фото] {text}" if has_photo and text else "[Фото]" if has_photo else text
            await message.reply(f"{hbold(hd.quote(key))}:\n{hd.quote(display)}")
        else:
            await message.reply(f"{hbold(hd.quote(key))}:\n{hd.quote(value)}")
        return

    if action == "del":
        if len(parts) < 3:
            await message.reply("Использование: /edit del [key]")
            return
        key = _normalize_key(parts[2])

        async with _PRESETS_LOCK:
            if _PRESETS_CACHE is None:
                _PRESETS_CACHE = await _load_presets_from_disk()

            if key not in _PRESETS_CACHE:
                await message.reply("Такого ключа нет.")
                return

            _PRESETS_CACHE.pop(key, None)
            await save_presets(_PRESETS_CACHE)

        await message.reply(f"✅ Удалил пресет: {hbold(hd.quote(key))}")
        return

    if action in {"add", "set", "upd", "update"}:
        if len(parts) < 3:
            await message.reply("Использование: /add [key] [text]\nИли ответом на сообщение/фото: /add [key]")
            return
        key = parts[2]
        extra_text = parts[3].strip() if len(parts) > 3 else None
        await _add_preset(message, manager, key, extra_text)
        return

    await message.reply("Неизвестная команда. Напиши /edit help.")


@router.message(Command("silent"))
async def handler(message: Message, manager: Manager, redis: PostgresStorage) -> None:
    """
    Toggles silent mode for a user in the group.
    If silent mode is disabled, it will be enabled, and vice versa.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: PostgresStorage object.
    :return: None
    """
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if not user_data: return None  # noqa

    if user_data.message_silent_mode:
        text = manager.text_message.get("silent_mode_disabled")
        with suppress(TelegramBadRequest):
            # Reply with the specified text
            await message.reply(text)

            # Unpin the chat message with the silent mode status
            await message.bot.unpin_chat_message(
                chat_id=message.chat.id,
                message_id=user_data.message_silent_id,
            )

        user_data.message_silent_mode = False
        user_data.message_silent_id = None
    else:
        text = manager.text_message.get("silent_mode_enabled")
        with suppress(TelegramBadRequest):
            # Reply with the specified text
            msg = await message.reply(text)

            # Pin the chat message with the silent mode status
            await msg.pin(disable_notification=True)

        user_data.message_silent_mode = True
        user_data.message_silent_id = msg.message_id

    await redis.update_user(user_data.id, user_data)


@router.message(Command("information"))
async def handler(message: Message, manager: Manager, redis: PostgresStorage) -> None:
    """
    Sends user information in response to the /information command.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: PostgresStorage object.
    :return: None
    """
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if not user_data: return None  # noqa

    user_info = await get_user_info(manager.config.api, user_data.id)

    if user_info:
        keys = await get_user_keys(manager.config.api, user_data.id)
        traffic_gb = await get_user_traffic(manager.config.remna, keys)
        text = format_user_info_message(user_info, keys, traffic_gb)
    else:
        url = f"https://t.me/{user_data.username[1:]}" if user_data.username != "-" else f"tg://user?id={user_data.id}"
        text = manager.text_message.get("user_started_bot")
        text = text.format(name=hlink(user_data.full_name, url), id=user_data.id)

    presets = await get_presets()
    bot_username = manager.config.api.BOT_USERNAME
    bot_link = f"https://t.me/{bot_username}?start=search_{user_data.id}"

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="Открыть в боте", url=bot_link))
    for key in sorted(presets.keys()):
        kb.button(text=key, callback_data=f"{ANS_CB_PREFIX}{key}")
    kb.adjust(1, 2)

    await message.reply(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@router.message(Command(commands=["ban"]))
async def handler(message: Message, manager: Manager, redis: PostgresStorage) -> None:
    """
    Toggles the ban status for a user in the group.
    If the user is banned, they will be unbanned, and vice versa.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: PostgresStorage object.
    :return: None
    """
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if not user_data: return None  # noqa

    if user_data.is_banned:
        user_data.is_banned = False
        text = manager.text_message.get("user_unblocked")
    else:
        user_data.is_banned = True
        text = manager.text_message.get("user_blocked")

    # Reply with the specified text
    await message.reply(text)
    await redis.update_user(user_data.id, user_data)

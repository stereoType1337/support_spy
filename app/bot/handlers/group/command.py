import asyncio
import json
from contextlib import suppress
from pathlib import Path
from typing import Any

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from aiogram.filters import Command, MagicData
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.markdown import hcode, hbold
from aiogram.utils.text_decorations import html_decoration as hd

from app.bot.manager import Manager
from app.bot.utils.redis import RedisStorage

router_id = Router()
router_id.message.filter(
    F.chat.type.in_(["group", "supergroup"]),
)


def _is_admin(message: Message, manager: Manager) -> bool:
    if not message.from_user:
        return False
    return (
        message.from_user.id == manager.config.bot.DEV_ID
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
_PRESETS_CACHE: dict[str, str] | None = None


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace(" ", "_")


async def _load_presets_from_disk() -> dict[str, str]:
    """
    Reads presets JSON from disk. If file doesn't exist, creates an empty one.
    """
    if not PRESETS_FILE.exists():
        PRESETS_FILE.write_text("{}", encoding="utf-8")

    raw = PRESETS_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return {}

    data: Any = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("ans_presets.json must contain a JSON object (dict)")

    out: dict[str, str] = {}
    for k, v in data.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        nk = _normalize_key(k)
        if nk:
            out[nk] = v
    return out


async def get_presets() -> dict[str, str]:
    """
    Cached presets read; reloadable.
    """
    global _PRESETS_CACHE
    async with _PRESETS_LOCK:
        if _PRESETS_CACHE is None:
            _PRESETS_CACHE = await _load_presets_from_disk()
        return dict(_PRESETS_CACHE)


async def reload_presets() -> dict[str, str]:
    global _PRESETS_CACHE
    async with _PRESETS_LOCK:
        _PRESETS_CACHE = await _load_presets_from_disk()
        return dict(_PRESETS_CACHE)


async def save_presets(presets: dict[str, str]) -> None:
    """
    Atomic-ish save to disk (write temp then replace).
    """
    tmp = PRESETS_FILE.with_suffix(".json.tmp")
    payload = json.dumps(presets, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.write_text(payload + "\n", encoding="utf-8")
    tmp.replace(PRESETS_FILE)


def build_ans_keyboard(presets: dict[str, str]) -> InlineKeyboardBuilder:
    """
    Builds inline keyboard from presets keys.
    """
    kb = InlineKeyboardBuilder()

    for key in sorted(presets.keys()):
        # callback_data — только технич. строка, HTML не нужен
        kb.button(text=key, callback_data=f"{ANS_CB_PREFIX}{key}")

    kb.adjust(2)
    return kb


@router.message(Command("ans"))
async def ans_command(message: Message, redis: RedisStorage) -> None:
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
async def ans_callback(callback: CallbackQuery, manager: Manager, redis: RedisStorage) -> None:
    """
    On preset button click: sends preset text to user напрямую, и подтверждает в топике.
    """
    if not callback.message or callback.message.message_thread_id is None:
        await callback.answer("Это можно использовать только в топиках.", show_alert=True)
        return

    preset_key = callback.data.split(":", 1)[1] if callback.data else ""
    preset_key = _normalize_key(preset_key)

    presets = await get_presets()
    preset_text = presets.get(preset_key)
    if not preset_text:
        await callback.answer("Пресет не найден (возможно обновили файл). Нажми /ans заново.", show_alert=True)
        return

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

    confirm = (
        f"✅ Отправлено пользователю пресетом: {hbold(hd.quote(preset_key))}"
        if ok
        else f"❌ Не удалось отправить: {hd.quote(error_text or 'ошибка')}"
    )

    with suppress(TelegramBadRequest):
        await callback.message.reply(confirm)


@router.message(Command("edit"))
async def edit_presets(message: Message, manager: Manager) -> None:
    """
    /edit — manage presets stored in ans_presets.json

    Commands:
      /edit
      /edit list
      /edit show [key]
      /edit add [key] [text...]
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
            "• /edit list\n"
            "• /edit show [key]\n"
            "• /edit add [key] [text]\n"
            "• /edit del [key]\n"
            "• /edit reload"
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
            await message.reply("Пресетов нет. Добавь через /edit add [key] [text].")
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
        text = presets.get(key)
        if not text:
            await message.reply("Не найдено.")
            return
        await message.reply(f"{hbold(hd.quote(key))}:\n{hd.quote(text)}")
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
        if len(parts) < 4:
            await message.reply("Использование: /edit add [key] [text]")
            return

        key = _normalize_key(parts[2])
        text = parts[3].strip()

        if not key:
            await message.reply("Ключ пустой/некорректный.")
            return
        if not text:
            await message.reply("Текст пустой.")
            return

        async with _PRESETS_LOCK:
            if _PRESETS_CACHE is None:
                _PRESETS_CACHE = await _load_presets_from_disk()

            _PRESETS_CACHE[key] = text
            await save_presets(_PRESETS_CACHE)

        await message.reply(f"✅ Сохранил пресет: {hbold(hd.quote(key))}")
        return

    await message.reply("Неизвестная команда. Напиши /edit help.")


@router.message(Command("silent"))
async def handler(message: Message, manager: Manager, redis: RedisStorage) -> None:
    """
    Toggles silent mode for a user in the group.
    If silent mode is disabled, it will be enabled, and vice versa.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: RedisStorage object.
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
async def handler(message: Message, manager: Manager, redis: RedisStorage) -> None:
    """
    Sends user information in response to the /information command.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: RedisStorage object.
    :return: None
    """
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if not user_data: return None  # noqa

    text = manager.text_message.get("user_information")
    # Reply with formatted user information
    await message.reply(text.format_map(user_data.to_dict()))


@router.message(Command(commands=["ban"]))
async def handler(message: Message, manager: Manager, redis: RedisStorage) -> None:
    """
    Toggles the ban status for a user in the group.
    If the user is banned, they will be unbanned, and vice versa.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: RedisStorage object.
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

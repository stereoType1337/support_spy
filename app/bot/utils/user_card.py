from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.markdown import hlink

from app.bot.manager import Manager
from app.bot.utils.api import format_user_info_message, get_user_info, pick_open_url
from app.bot.utils.postgres.models import UserData

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
ANS_CB_PREFIX = "ans:"
INFO_REFRESH_CB = "info:refresh"


def user_link(user_data: UserData) -> str:
    if user_data.username and user_data.username != "-":
        url = f"https://t.me/{user_data.username.lstrip('@')}"
    else:
        url = f"tg://user?id={user_data.id}"
    return hlink(user_data.full_name, url)


async def build_user_card(manager: Manager, user_data: UserData) -> tuple[str, str]:
    info = await get_user_info(manager.config.notspy, user_data.id)
    source = user_data.source_bot_id
    open_url = pick_open_url(info, manager.config.notspy.BOT_USERNAME, source)
    if info:
        return format_user_info_message(info, user_link(user_data), source), open_url

    text = manager.group_text.get("user_started_bot").format(
        name=user_link(user_data),
        id=user_data.id,
        username=user_data.username or "-",
        language=user_data.language_code or "-",
        created_at=user_data.created_at[:16],
    )
    return text, open_url


def build_topic_keyboard(open_url: str, presets: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="Открыть в боте", url=open_url))
    kb.row(InlineKeyboardButton(text="🔄 Обновить информацию", callback_data=INFO_REFRESH_CB))
    preset_buttons = [
        InlineKeyboardButton(text=key, callback_data=f"{ANS_CB_PREFIX}{key}")
        for key in sorted(presets.keys())
    ]
    for i in range(0, len(preset_buttons), 2):
        kb.row(*preset_buttons[i:i + 2])
    return kb.as_markup()

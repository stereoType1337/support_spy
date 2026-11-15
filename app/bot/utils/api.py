import logging
from datetime import datetime

import aiohttp

from app.config import NotspyConfig

logger = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=5)


async def get_user_info(config: NotspyConfig, user_tg_id: int) -> dict | None:
    if not config.enabled:
        return None
    url = f"{config.URL}/api/support/users/{user_tg_id}"
    headers = {"X-Token": config.TOKEN, "accept": "application/json"}
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                if response.status != 404:
                    logger.warning("notspy_api_status=%s user=%s", response.status, user_tg_id)
    except Exception:
        logger.warning("notspy_api_failed user=%s", user_tg_id, exc_info=True)
    return None


def _date(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y")
    except ValueError:
        return value


def _datetime(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return value


def _flag(value: bool) -> str:
    return "✅" if value else "❌"


def format_bot_block(bot: dict) -> str:
    title = f"@{bot['bot_username']}" if bot.get("bot_username") else f"bot_id {bot['bot_id']}"
    if bot.get("is_main"):
        title += " (основной)"
    lines = [
        f"🤖 <b>{title}</b>",
        f"Подключён: {_flag(bot.get('is_connected', False))}",
        f"Premium: {_flag(bot.get('is_premium', False))}",
        f"Старт: {_date(bot.get('started_at'))} · Активность: {_date(bot.get('last_active'))}",
    ]
    if bot.get("utm"):
        lines.append(f"UTM: {bot['utm']}")
    if bot.get("is_blocked"):
        lines.append(f"🚫 Заблокировал бота {_date(bot.get('blocked_at'))}")

    sub = bot.get("subscription")
    if sub:
        lines.append(
            f"💎 Подписка: {sub['status']} {_flag(sub['is_active'])} "
            f"до {_datetime(sub.get('expires_at'))} ({sub.get('days_left', 0)} дн.)"
        )
    else:
        lines.append("💎 Подписки нет")

    ref = bot.get("referral")
    if ref and (ref.get("invited") or ref.get("earned_total")):
        lines.append(
            f"💰 Рефералы: {ref['invited']} · баланс {ref['balance']} ₽ "
            f"(заработано {ref['earned_total']}, выведено {ref['withdrawn_total']})"
        )
    return "\n".join(lines)


def format_user_info_message(info: dict, name_link: str) -> str:
    bots = info.get("bots", [])
    first = bots[0] if bots else {}
    username = f"@{first['username']}" if first.get("username") else "—"
    header = (
        f"👤 {name_link}\n\n"
        f"<b>ID:</b> <code>{info['chat_id']}</code>\n"
        f"<b>Username:</b> {username}\n"
    )
    blocks = [format_bot_block(bot) for bot in bots]
    return header + "\n" + "\n\n".join(blocks)


def pick_open_url(info: dict | None, fallback_username: str) -> str:
    if info:
        for bot in info.get("bots", []):
            if bot.get("deeplink"):
                return bot["deeplink"]
    return f"https://t.me/{fallback_username}"

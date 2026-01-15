from typing import Optional, List, Dict, Any
import aiohttp
from datetime import datetime

from app.config import ApiConfig


async def get_user_info(api_config: ApiConfig, user_tg_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает информацию о пользователе из API.

    :param api_config: Конфигурация API.
    :param user_tg_id: Telegram ID пользователя.
    :return: Словарь с информацией о пользователе или None в случае ошибки.
    """
    url = f"{api_config.URL}/users/{user_tg_id}"
    params = {"tg_id": api_config.ADMIN_TG_ID}
    headers = {
        "accept": "application/json",
        "X-Token": api_config.TOKEN,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                return None
    except Exception:
        return None


async def get_user_keys(api_config: ApiConfig, user_tg_id: int) -> List[Dict[str, Any]]:
    """
    Получает список ключей пользователя из API.

    :param api_config: Конфигурация API.
    :param user_tg_id: Telegram ID пользователя.
    :return: Список словарей с информацией о ключах пользователя.
    """
    url = f"{api_config.URL}/keys/all/{user_tg_id}"
    params = {"tg_id": api_config.ADMIN_TG_ID}
    headers = {
        "accept": "application/json",
        "X-Token": api_config.TOKEN,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                return []
    except Exception:
        return []


def format_user_info_message(user_info: Dict[str, Any], keys: List[Dict[str, Any]]) -> str:
    """
    Форматирует сообщение с информацией о пользователе и его ключах.

    :param user_info: Информация о пользователе.
    :param keys: Список ключей пользователя.
    :return: Отформатированное сообщение.
    """
    # Форматирование информации о пользователе
    tg_id = user_info.get("tg_id", "N/A")
    username = user_info.get("username", "N/A")
    username = f"@{username}" if username != "N/A" else "N/A"
    first_name = user_info.get("first_name", "")
    last_name = user_info.get("last_name") or ""
    full_name = f"{first_name} {last_name}".strip() or "N/A"
    balance = user_info.get("balance", 0)
    # Форматируем баланс с одной десятичной цифрой
    balance_str = f"{balance:.1f}" if isinstance(balance, (int, float)) else str(balance)
    trial = user_info.get("trial", 0)
    
    # Форматирование даты регистрации
    created_at = user_info.get("created_at", "")
    if created_at:
        try:
            # Парсим ISO формат: 2025-09-08T08:04:43.178238
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            reg_date = dt.strftime("%d.%m.%Y")
        except Exception:
            reg_date = created_at[:10] if len(created_at) >= 10 else created_at
    else:
        reg_date = "N/A"

    # Статус регистрации
    status = "Зарегистрирован в боте"

    message_parts = [
        "👤 <b>Информация о пользователе:</b>",
        f"",
        f"🆔 <b>Telegram ID:</b> {tg_id}",
        f"✅ <b>Статус:</b> {status}",
        f"👨‍💼 <b>Username:</b> {username}",
        f"📝 <b>Имя:</b> {full_name}",
        f"💰 <b>Баланс:</b> {balance_str} руб.",
        f"🎯 <b>Триал:</b> {trial}",
        f"📅 <b>Дата регистрации:</b> {reg_date}",
    ]

    # Форматирование ключей
    if keys:
        message_parts.append("")
        message_parts.append(f"🔑 <b>Ключи пользователя ({len(keys)}):</b>")
        message_parts.append("")
        
        for idx, key in enumerate(keys, 1):
            email = key.get("email", "N/A")
            server_id = key.get("server_id", "N/A")
            
            # Форматирование даты истечения
            expiry_time = key.get("expiry_time")
            if expiry_time:
                try:
                    # expiry_time в миллисекундах
                    expiry_dt = datetime.fromtimestamp(expiry_time / 1000)
                    expiry_str = expiry_dt.strftime("%d.%m.%Y %H:%M")
                except Exception:
                    expiry_str = str(expiry_time)
            else:
                expiry_str = "N/A"

            message_parts.append(f"   {idx}. {email}")
            message_parts.append(f"      ⏰ <b>Истекает:</b> {expiry_str}")
            message_parts.append(f"      🖥 <b>Сервер:</b> {server_id}")
            if idx < len(keys):
                message_parts.append("")

    return "\n".join(message_parts)


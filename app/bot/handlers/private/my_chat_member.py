from aiogram import Router, F
from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatMemberUpdated

from app.bot.manager import Manager
from app.bot.utils.postgres import PostgresStorage
from app.bot.utils.postgres.models import UserData
from app.bot.utils.user_card import NO_PREVIEW, user_link

router = Router()
router.my_chat_member.filter(F.chat.type == "private")


@router.my_chat_member()
async def handle_chat_member_update(
        update: ChatMemberUpdated,
        redis: PostgresStorage,
        user_data: UserData,
        manager: Manager,
) -> None:
    """
    Handle updates of the bot chat member status.

    :param update: ChatMemberUpdated object.
    :param redis: PostgresStorage object.
    :param user_data: UserData object.
    :param manager: Manager object.
    :return: None
    """
    # Update the user's state based on the new chat member status
    user_data.state = update.new_chat_member.status
    await redis.update_user(user_data.id, user_data)

    if user_data.state == ChatMemberStatus.MEMBER:
        text = manager.group_text.get("user_restarted_bot")
    else:
        text = manager.group_text.get("user_stopped_bot")

    await update.bot.send_message(
        chat_id=manager.config.bot.GROUP_ID,
        text=text.format(name=user_link(user_data)),
        message_thread_id=user_data.message_thread_id,
        link_preview_options=NO_PREVIEW,
    )

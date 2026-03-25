from datetime import datetime, timezone, timedelta

from aiogram import Router, F
from aiogram.filters import Command, MagicData
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.manager import Manager
from app.bot.utils.postgres.stats import StatsStorage

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

# Callback data prefixes
STATS_PREFIX = "stats_"
STATS_PERIOD_PREFIX = "stats_period_"
STATS_CSV_PREFIX = "stats_csv_"


def build_stats_keyboard() -> InlineKeyboardBuilder:
    """Build keyboard for stats command."""
    kb = InlineKeyboardBuilder()

    # Кнопки периодов статистики
    kb.button(text="📊 1 день", callback_data=f"{STATS_PERIOD_PREFIX}1")
    kb.button(text="📊 7 дней", callback_data=f"{STATS_PERIOD_PREFIX}7")
    kb.button(text="📊 30 дней", callback_data=f"{STATS_PERIOD_PREFIX}30")
    kb.button(text="📊 Всё время", callback_data=f"{STATS_PERIOD_PREFIX}all")

    # Кнопки экспорта CSV
    kb.button(text="📥 CSV 1 день", callback_data=f"{STATS_CSV_PREFIX}1")
    kb.button(text="📥 CSV 7 дней", callback_data=f"{STATS_CSV_PREFIX}7")
    kb.button(text="📥 CSV 30 дней", callback_data=f"{STATS_CSV_PREFIX}30")
    kb.button(text="📥 CSV всё время", callback_data=f"{STATS_CSV_PREFIX}all")

    kb.adjust(4, 4)
    return kb


def format_stats_message(stats: dict, period_name: str) -> str:
    """Format statistics into a readable message."""
    lines = [
        f"📊 <b>Статистика за {period_name}</b>\n",
        f"🆕 Новых топиков: <b>{stats['new_topics']}</b>",
        f"💬 Активных топиков: <b>{stats['active_topics']}</b>",
        f"📨 Сообщений от пользователей: <b>{stats['total_user_messages']}</b>\n",
    ]

    if stats['responder_stats']:
        lines.append("👥 <b>Статистика ответов:</b>")
        # Сортируем по количеству уникальных топиков
        sorted_responders = sorted(
            stats['responder_stats'].items(),
            key=lambda x: (x[1]['unique_topics'], x[1]['total_messages']),
            reverse=True
        )
        for resp_id, data in sorted_responders:
            lines.append(
                f"  • {data['name']}: "
                f"<b>{data['unique_topics']}</b> топиков, "
                f"<b>{data['total_messages']}</b> сообщений"
            )
    else:
        lines.append("👥 Нет данных об ответах за этот период")

    return "\n".join(lines)


@router.message(
    Command("stats"),
    MagicData(F.event_from_user.id.in_(F.config.bot.DEV_IDS)),
)
async def handle_stats_command(message: Message, manager: Manager, stats_storage: StatsStorage) -> None:
    """Handle /stats command - show statistics menu."""
    kb = build_stats_keyboard()

    await message.answer(
        "📊 <b>Статистика бота поддержки</b>\n\n"
        "Выберите период для просмотра статистики или экспортируйте данные в CSV:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await manager.delete_message(message)


@router.callback_query(F.data.startswith(STATS_PERIOD_PREFIX))
async def handle_stats_period(call: CallbackQuery, stats_storage: StatsStorage) -> None:
    """Handle period selection for statistics."""
    period = call.data.replace(STATS_PERIOD_PREFIX, "")

    if period == "all":
        days = None
        period_name = "всё время"
    else:
        days = int(period)
        period_name = f"{days} {'день' if days == 1 else 'дней'}"

    stats = await stats_storage.get_stats_by_period(days)
    text = format_stats_message(stats, period_name)

    kb = build_stats_keyboard()

    await call.message.edit_text(
        text,
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith(STATS_CSV_PREFIX))
async def handle_stats_csv(call: CallbackQuery, stats_storage: StatsStorage) -> None:
    """Handle CSV export request."""
    period = call.data.replace(STATS_CSV_PREFIX, "")

    if period == "all":
        days = None
        period_name = "all_time"
    else:
        days = int(period)
        period_name = f"{days}_days"

    csv_content = await stats_storage.export_topics_csv(days=days)

    # Создаем файл
    now = datetime.now(timezone(timedelta(hours=3)))
    filename = f"topics_stats_{period_name}_{now.strftime('%Y%m%d_%H%M%S')}.csv"

    file = BufferedInputFile(
        csv_content.encode('utf-8-sig'),  # utf-8-sig for Excel compatibility
        filename=filename
    )

    await call.message.answer_document(
        file,
        caption=f"📥 Экспорт топиков за {period_name.replace('_', ' ')}"
    )
    await call.answer("Файл отправлен!")

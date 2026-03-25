import asyncpg

from .models import UserData


class PostgresStorage:
    """Class for managing user data storage using PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def get_user(self, id_: int) -> UserData | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", id_)
            if row is None:
                return None
            return self._row_to_user(row)

    async def update_user(self, id_: int, data: UserData) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (
                    id, message_thread_id, message_silent_id, message_silent_mode,
                    full_name, username, state, is_banned, language_code,
                    created_at, has_sent_message, has_bot_replied,
                    is_bot_stopped, is_bot_restarted
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                ON CONFLICT (id) DO UPDATE SET
                    message_thread_id = EXCLUDED.message_thread_id,
                    message_silent_id = EXCLUDED.message_silent_id,
                    message_silent_mode = EXCLUDED.message_silent_mode,
                    full_name = EXCLUDED.full_name,
                    username = EXCLUDED.username,
                    state = EXCLUDED.state,
                    is_banned = EXCLUDED.is_banned,
                    language_code = EXCLUDED.language_code,
                    created_at = EXCLUDED.created_at,
                    has_sent_message = EXCLUDED.has_sent_message,
                    has_bot_replied = EXCLUDED.has_bot_replied,
                    is_bot_stopped = EXCLUDED.is_bot_stopped,
                    is_bot_restarted = EXCLUDED.is_bot_restarted
            """,
                data.id, data.message_thread_id, data.message_silent_id,
                data.message_silent_mode, data.full_name, data.username,
                data.state, data.is_banned, data.language_code,
                data.created_at, data.has_sent_message, data.has_bot_replied,
                data.is_bot_stopped, data.is_bot_restarted,
            )

    async def get_by_message_thread_id(self, message_thread_id: int) -> UserData | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE message_thread_id = $1 LIMIT 1",
                message_thread_id,
            )
            if row is None:
                return None
            return self._row_to_user(row)

    async def get_all_users_ids(self) -> list[int]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id FROM users")
            return [row["id"] for row in rows]

    async def get_all_users(self) -> list[UserData]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM users")
            return [self._row_to_user(row) for row in rows]

    @staticmethod
    def _row_to_user(row: asyncpg.Record) -> UserData:
        return UserData(
            id=row["id"],
            message_thread_id=row["message_thread_id"],
            message_silent_id=row["message_silent_id"],
            message_silent_mode=row["message_silent_mode"],
            full_name=row["full_name"],
            username=row["username"],
            state=row["state"],
            is_banned=row["is_banned"],
            language_code=row["language_code"],
            created_at=row["created_at"],
            has_sent_message=row["has_sent_message"],
            has_bot_replied=row["has_bot_replied"],
            is_bot_stopped=row["is_bot_stopped"],
            is_bot_restarted=row["is_bot_restarted"],
        )

import asyncpg


async def create_pool(dsn: str) -> asyncpg.Pool:
    """Create and return an asyncpg connection pool."""
    return await asyncpg.create_pool(dsn, min_size=2, max_size=10)


async def init_db(pool: asyncpg.Pool) -> None:
    """Create tables if they don't exist."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                message_thread_id BIGINT,
                message_silent_id BIGINT,
                message_silent_mode BOOLEAN NOT NULL DEFAULT FALSE,
                full_name VARCHAR(255) NOT NULL,
                username VARCHAR(255),
                state VARCHAR(50) NOT NULL DEFAULT 'member',
                is_banned BOOLEAN NOT NULL DEFAULT FALSE,
                language_code VARCHAR(10),
                created_at VARCHAR(50) NOT NULL,
                has_sent_message BOOLEAN NOT NULL DEFAULT FALSE,
                has_bot_replied BOOLEAN NOT NULL DEFAULT FALSE,
                is_bot_stopped BOOLEAN NOT NULL DEFAULT FALSE,
                is_bot_restarted BOOLEAN NOT NULL DEFAULT FALSE
            );

            ALTER TABLE users ADD COLUMN IF NOT EXISTS source_bot_id BIGINT;

            CREATE INDEX IF NOT EXISTS idx_users_message_thread_id
                ON users(message_thread_id) WHERE message_thread_id IS NOT NULL;

            CREATE TABLE IF NOT EXISTS topic_stats (
                message_thread_id BIGINT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                user_name VARCHAR(255) NOT NULL,
                username VARCHAR(255),
                topic_link VARCHAR(512) NOT NULL,
                created_at VARCHAR(50) NOT NULL,
                updated_at VARCHAR(50) NOT NULL,
                total_messages INTEGER NOT NULL DEFAULT 0,
                responder_counts JSONB NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS message_stats (
                id SERIAL PRIMARY KEY,
                message_thread_id BIGINT NOT NULL,
                responder_id BIGINT NOT NULL,
                responder_name VARCHAR(255) NOT NULL,
                timestamp VARCHAR(50) NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_message_stats_timestamp
                ON message_stats(timestamp);
            CREATE INDEX IF NOT EXISTS idx_message_stats_thread_id
                ON message_stats(message_thread_id);
        """)

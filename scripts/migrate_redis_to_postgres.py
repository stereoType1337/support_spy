"""
One-time migration script: Redis -> PostgreSQL.

Usage:
    pip install redis asyncpg
    python scripts/migrate_redis_to_postgres.py

Set environment variables or edit the constants below.
"""
import asyncio
import json
import os

import asyncpg
from dotenv import load_dotenv
from redis.asyncio import Redis

load_dotenv()

PG_USER = os.getenv("POSTGRES_USER", "bot")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "")
PG_HOST = os.getenv("POSTGRES_HOST", "postgres")
PG_PORT = os.getenv("POSTGRES_PORT", "5432")
PG_DB = os.getenv("POSTGRES_DB", "support_bot")

REDIS_HOST = os.getenv("REDIS_HOST", "support-redis-ray")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_DB = os.getenv("REDIS_DB", "1")
REDIS_URL = os.getenv("REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")
POSTGRES_DSN = f"postgresql://{PG_USER}:{PG_PASS}@{PG_HOST}:{PG_PORT}/{PG_DB}"


async def main() -> None:
    print(f"Connecting to Redis: {REDIS_URL}")
    print(f"Connecting to PostgreSQL: {PG_HOST}:{PG_PORT}/{PG_DB}")

    redis = Redis.from_url(REDIS_URL)
    pool = await asyncpg.create_pool(POSTGRES_DSN)

    async with pool.acquire() as conn:
        # Create tables
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
        print("Tables created")

        # --- Migrate users ---
        # Сначала получаем существующих пользователей из PostgreSQL,
        # чтобы сохранить данные, накопленные после первой миграции
        existing_users = {}
        rows = await conn.fetch("SELECT id, message_thread_id FROM users")
        for row in rows:
            existing_users[row["id"]] = row["message_thread_id"]
        print(f"Existing users in PostgreSQL: {len(existing_users)}")

        user_ids = await redis.hkeys("users")
        inserted = 0
        updated = 0
        skipped = 0
        for uid in user_ids:
            raw = await redis.hget("users", uid)
            if not raw:
                continue
            data = json.loads(raw)
            user_id = int(data["id"])
            redis_thread_id = data.get("message_thread_id")

            if user_id in existing_users:
                pg_thread_id = existing_users[user_id]
                if pg_thread_id is None and redis_thread_id is not None:
                    # В PostgreSQL нет thread_id, но в Redis есть — восстанавливаем
                    await conn.execute(
                        "UPDATE users SET message_thread_id = $1 WHERE id = $2",
                        redis_thread_id, user_id,
                    )
                    updated += 1
                elif pg_thread_id is not None and redis_thread_id is not None and pg_thread_id != redis_thread_id:
                    # Оба есть но разные — берём более новый (больший thread_id)
                    newer_tid = max(pg_thread_id, redis_thread_id)
                    if newer_tid != pg_thread_id:
                        await conn.execute(
                            "UPDATE users SET message_thread_id = $1 WHERE id = $2",
                            newer_tid, user_id,
                        )
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
            else:
                # Новый пользователь — вставляем
                await conn.execute("""
                    INSERT INTO users (
                        id, message_thread_id, message_silent_id, message_silent_mode,
                        full_name, username, state, is_banned, language_code,
                        created_at, has_sent_message, has_bot_replied,
                        is_bot_stopped, is_bot_restarted
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                    ON CONFLICT (id) DO NOTHING
                """,
                    user_id,
                    redis_thread_id,
                    data.get("message_silent_id"),
                    bool(data.get("message_silent_mode", False)),
                    data.get("full_name", ""),
                    data.get("username"),
                    data.get("state", "member"),
                    bool(data.get("is_banned", False)),
                    data.get("language_code"),
                    data.get("created_at", ""),
                    bool(data.get("has_sent_message", False)),
                    bool(data.get("has_bot_replied", False)),
                    bool(data.get("is_bot_stopped", False)),
                    bool(data.get("is_bot_restarted", False)),
                )
                inserted += 1

        print(f"Users: {inserted} inserted, {updated} updated thread_id, {skipped} skipped")

        # --- Migrate topic_stats ---
        topic_data = await redis.hgetall("topic_stats")
        migrated_topics = 0
        for key, raw in topic_data.items():
            data = json.loads(raw)
            await conn.execute("""
                INSERT INTO topic_stats (
                    message_thread_id, user_id, user_name, username,
                    topic_link, created_at, updated_at, total_messages, responder_counts
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (message_thread_id) DO NOTHING
            """,
                int(data["message_thread_id"]),
                int(data["user_id"]),
                data.get("user_name", ""),
                data.get("username"),
                data.get("topic_link", ""),
                data.get("created_at", ""),
                data.get("updated_at", ""),
                int(data.get("total_messages", 0)),
                json.dumps(data.get("responder_counts", {})),
            )
            migrated_topics += 1

        print(f"Migrated {migrated_topics} topic stats")

        # --- Migrate message_stats ---
        msg_data = await redis.hgetall("message_stats")
        migrated_msgs = 0
        for key, raw in msg_data.items():
            data = json.loads(raw)
            await conn.execute("""
                INSERT INTO message_stats (
                    message_thread_id, responder_id, responder_name, timestamp
                ) VALUES ($1,$2,$3,$4)
            """,
                int(data["message_thread_id"]),
                int(data["responder_id"]),
                data.get("responder_name", ""),
                data.get("timestamp", ""),
            )
            migrated_msgs += 1

        print(f"Migrated {migrated_msgs} message stats")

    await pool.close()
    await redis.close()
    print("Migration complete!")


if __name__ == "__main__":
    asyncio.run(main())

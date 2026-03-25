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
from redis.asyncio import Redis


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://bot:bot_secret_password@localhost:5432/support_bot")


async def main() -> None:
    redis = Redis.from_url(REDIS_URL)
    pool = await asyncpg.create_pool(POSTGRES_DSN)

    async with pool.acquire() as conn:
        # --- Migrate users ---
        user_ids = await redis.hkeys("users")
        migrated_users = 0
        for uid in user_ids:
            raw = await redis.hget("users", uid)
            if not raw:
                continue
            data = json.loads(raw)
            await conn.execute("""
                INSERT INTO users (
                    id, message_thread_id, message_silent_id, message_silent_mode,
                    full_name, username, state, is_banned, language_code,
                    created_at, has_sent_message, has_bot_replied,
                    is_bot_stopped, is_bot_restarted
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                ON CONFLICT (id) DO NOTHING
            """,
                int(data["id"]),
                data.get("message_thread_id"),
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
            migrated_users += 1

        print(f"Migrated {migrated_users} users")

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

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List

import asyncpg


@dataclass
class TopicStats:
    """Data class representing topic statistics."""
    user_id: int
    user_name: str
    username: str | None
    message_thread_id: int
    topic_link: str
    created_at: str
    updated_at: str
    total_messages: int = 0
    responder_counts: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TopicStats":
        return cls(**data)


class StatsStorage:
    """Class for managing topic statistics storage using PostgreSQL."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def get_topic_stats(self, message_thread_id: int) -> TopicStats | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM topic_stats WHERE message_thread_id = $1",
                message_thread_id,
            )
            if row is None:
                return None
            return self._row_to_topic(row)

    async def create_or_update_topic(
        self,
        user_id: int,
        user_name: str,
        username: str | None,
        message_thread_id: int,
        group_id: int,
    ) -> TopicStats:
        now = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
        topic_link = f"https://t.me/c/{str(group_id)[4:]}/{message_thread_id}"

        async with self.pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT * FROM topic_stats WHERE message_thread_id = $1",
                message_thread_id,
            )
            if existing:
                await conn.execute("""
                    UPDATE topic_stats
                    SET updated_at = $1, total_messages = total_messages + 1,
                        user_name = $2, username = $3
                    WHERE message_thread_id = $4
                """, now, user_name, username, message_thread_id)
                topic = self._row_to_topic(existing)
                topic.updated_at = now
                topic.total_messages += 1
                topic.user_name = user_name
                topic.username = username
                return topic
            else:
                await conn.execute("""
                    INSERT INTO topic_stats
                        (message_thread_id, user_id, user_name, username,
                         topic_link, created_at, updated_at, total_messages, responder_counts)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                """,
                    message_thread_id, user_id, user_name, username,
                    topic_link, now, now, 1, json.dumps({}),
                )
                return TopicStats(
                    user_id=user_id, user_name=user_name, username=username,
                    message_thread_id=message_thread_id, topic_link=topic_link,
                    created_at=now, updated_at=now, total_messages=1,
                    responder_counts={},
                )

    async def record_response(
        self,
        message_thread_id: int,
        responder_id: int,
        responder_name: str,
    ) -> None:
        now = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
        responder_key = str(responder_id)

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT responder_counts FROM topic_stats WHERE message_thread_id = $1",
                message_thread_id,
            )
            if not row:
                return

            counts = json.loads(row["responder_counts"])
            counts[responder_key] = counts.get(responder_key, 0) + 1

            await conn.execute("""
                UPDATE topic_stats
                SET responder_counts = $1, updated_at = $2
                WHERE message_thread_id = $3
            """, json.dumps(counts), now, message_thread_id)

            await conn.execute("""
                INSERT INTO message_stats
                    (message_thread_id, responder_id, responder_name, timestamp)
                VALUES ($1,$2,$3,$4)
            """, message_thread_id, responder_id, responder_name, now)

    async def get_unanswered_topics_today(self) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT u.id, u.full_name, u.username, u.message_thread_id,
                       ts.topic_link, ts.created_at
                FROM users u
                JOIN topic_stats ts ON u.message_thread_id = ts.message_thread_id
                WHERE u.has_sent_message = true
                  AND u.has_bot_replied = false
                  AND u.is_banned = false
                  AND u.is_bot_stopped = false
                  AND u.state != 'kicked'
                  AND ts.responder_counts = '{}'
                  AND ts.updated_at::date = CURRENT_DATE
                ORDER BY ts.updated_at
            """)
            return [
                {
                    "id": row["id"],
                    "full_name": row["full_name"],
                    "username": row["username"],
                    "message_thread_id": row["message_thread_id"],
                    "topic_link": row["topic_link"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

    async def get_all_topics(self) -> List[TopicStats]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM topic_stats")
            return [self._row_to_topic(row) for row in rows]

    async def get_all_messages(self) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM message_stats")
            return [
                {
                    "message_thread_id": row["message_thread_id"],
                    "responder_id": row["responder_id"],
                    "responder_name": row["responder_name"],
                    "timestamp": row["timestamp"],
                }
                for row in rows
            ]

    async def get_stats_by_period(self, days: int | None = None) -> dict:
        now = datetime.now(timezone(timedelta(hours=3)))
        if days:
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            cutoff = today_start - timedelta(days=days - 1)
            cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        else:
            cutoff_str = None

        async with self.pool.acquire() as conn:
            # Count new topics
            if cutoff_str:
                new_topics = await conn.fetchval(
                    "SELECT COUNT(*) FROM topic_stats WHERE created_at >= $1", cutoff_str)
                active_rows = await conn.fetch(
                    "SELECT total_messages FROM topic_stats WHERE updated_at >= $1", cutoff_str)
                messages = await conn.fetch(
                    "SELECT * FROM message_stats WHERE timestamp >= $1", cutoff_str)
            else:
                new_topics = await conn.fetchval("SELECT COUNT(*) FROM topic_stats")
                active_rows = await conn.fetch("SELECT total_messages FROM topic_stats")
                messages = await conn.fetch("SELECT * FROM message_stats")

        active_topics = len(active_rows)
        total_user_messages = sum(row["total_messages"] for row in active_rows)

        responder_stats: Dict[str, dict] = {}
        for msg in messages:
            responder_id = str(msg["responder_id"])
            responder_name = msg["responder_name"]
            thread_id = msg["message_thread_id"]

            if responder_id not in responder_stats:
                responder_stats[responder_id] = {
                    "name": responder_name,
                    "unique_topics": set(),
                    "total_messages": 0,
                }
            responder_stats[responder_id]["unique_topics"].add(thread_id)
            responder_stats[responder_id]["total_messages"] += 1

        for resp_id in responder_stats:
            responder_stats[resp_id]["unique_topics"] = len(responder_stats[resp_id]["unique_topics"])

        return {
            "new_topics": new_topics,
            "active_topics": active_topics,
            "total_user_messages": total_user_messages,
            "responder_stats": responder_stats,
        }

    async def export_topics_csv(self, days: int | None = None) -> str:
        now = datetime.now(timezone(timedelta(hours=3)))
        if days:
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            cutoff = today_start - timedelta(days=days - 1)
            cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        else:
            cutoff_str = None

        async with self.pool.acquire() as conn:
            if cutoff_str:
                topic_rows = await conn.fetch(
                    "SELECT * FROM topic_stats WHERE updated_at >= $1", cutoff_str)
                msg_rows = await conn.fetch(
                    "SELECT * FROM message_stats WHERE timestamp >= $1", cutoff_str)
            else:
                topic_rows = await conn.fetch("SELECT * FROM topic_stats")
                msg_rows = await conn.fetch("SELECT * FROM message_stats")

        filtered_topics = [self._row_to_topic(row) for row in topic_rows]

        # Collect responder names
        responder_names: Dict[str, str] = {}
        for msg in msg_rows:
            resp_id = str(msg["responder_id"])
            responder_names[resp_id] = msg["responder_name"]

        for topic in filtered_topics:
            for resp_id in topic.responder_counts.keys():
                if resp_id not in responder_names:
                    responder_names[resp_id] = resp_id

        sorted_responder_ids = sorted(responder_names.keys(), key=lambda x: int(x))

        if sorted_responder_ids:
            responder_columns = [responder_names[rid].replace(",", " ").replace('"', "'") for rid in sorted_responder_ids]
            header = "user_id,user_name,username,topic_link,created_at,updated_at,total_messages," + ",".join(f'"{col}"' for col in responder_columns)
        else:
            header = "user_id,user_name,username,topic_link,created_at,updated_at,total_messages"

        lines = [header]

        for topic in filtered_topics:
            user_name = topic.user_name.replace(",", " ").replace('"', "'")
            username = (topic.username or "-").replace(",", " ")

            base = f'{topic.user_id},"{user_name}",{username},{topic.topic_link},{topic.created_at},{topic.updated_at},{topic.total_messages}'

            if sorted_responder_ids:
                counts = [str(topic.responder_counts.get(rid, 0)) for rid in sorted_responder_ids]
                line = base + "," + ",".join(counts)
            else:
                line = base

            lines.append(line)

        return "\n".join(lines)

    @staticmethod
    def _row_to_topic(row: asyncpg.Record) -> TopicStats:
        counts = row["responder_counts"]
        if isinstance(counts, str):
            counts = json.loads(counts)
        return TopicStats(
            user_id=row["user_id"],
            user_name=row["user_name"],
            username=row["username"],
            message_thread_id=row["message_thread_id"],
            topic_link=row["topic_link"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            total_messages=row["total_messages"],
            responder_counts=counts,
        )

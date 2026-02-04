import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from redis.asyncio import Redis


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
    total_messages: int = 0  # Общее кол-во сообщений от пользователя
    responder_counts: Dict[str, int] = field(default_factory=dict)  # {user_id: count} - кто и сколько ответил

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TopicStats":
        return cls(**data)


class StatsStorage:
    """Class for managing topic statistics storage using Redis."""

    NAME = "topic_stats"
    MESSAGES_NAME = "message_stats"  # Для хранения сообщений от модераторов

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def _get(self, name: str, key: str | int) -> bytes | None:
        async with self.redis.client() as client:
            return await client.hget(name, key)

    async def _set(self, name: str, key: str | int, value: any) -> None:
        async with self.redis.client() as client:
            await client.hset(name, key, value)

    async def _get_all(self, name: str) -> dict:
        async with self.redis.client() as client:
            return await client.hgetall(name)

    async def get_topic_stats(self, message_thread_id: int) -> TopicStats | None:
        """Get topic stats by message_thread_id."""
        data = await self._get(self.NAME, message_thread_id)
        if data:
            return TopicStats.from_dict(json.loads(data))
        return None

    async def create_or_update_topic(
        self,
        user_id: int,
        user_name: str,
        username: str | None,
        message_thread_id: int,
        group_id: int,
    ) -> TopicStats:
        """Create or update topic stats when a topic is created or user sends a message."""
        now = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
        topic_link = f"https://t.me/c/{str(group_id)[4:]}/{message_thread_id}"

        existing = await self.get_topic_stats(message_thread_id)
        if existing:
            existing.updated_at = now
            existing.total_messages += 1
            existing.user_name = user_name
            existing.username = username
            await self._set(self.NAME, message_thread_id, json.dumps(existing.to_dict()))
            return existing
        else:
            stats = TopicStats(
                user_id=user_id,
                user_name=user_name,
                username=username,
                message_thread_id=message_thread_id,
                topic_link=topic_link,
                created_at=now,
                updated_at=now,
                total_messages=1,
                responder_counts={},
            )
            await self._set(self.NAME, message_thread_id, json.dumps(stats.to_dict()))
            return stats

    async def record_response(
        self,
        message_thread_id: int,
        responder_id: int,
        responder_name: str,
    ) -> None:
        """Record a response from a moderator/support agent."""
        stats = await self.get_topic_stats(message_thread_id)
        if not stats:
            return

        now = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
        stats.updated_at = now

        # Увеличиваем счётчик ответов для этого респондента
        responder_key = str(responder_id)
        stats.responder_counts[responder_key] = stats.responder_counts.get(responder_key, 0) + 1

        await self._set(self.NAME, message_thread_id, json.dumps(stats.to_dict()))

        # Также сохраняем отдельную запись для статистики по времени
        msg_record = {
            "message_thread_id": message_thread_id,
            "responder_id": responder_id,
            "responder_name": responder_name,
            "timestamp": now,
        }
        msg_key = f"{message_thread_id}_{now}_{responder_id}"
        await self._set(self.MESSAGES_NAME, msg_key, json.dumps(msg_record))

    async def get_all_topics(self) -> List[TopicStats]:
        """Get all topic stats."""
        data = await self._get_all(self.NAME)
        topics = []
        for key, value in data.items():
            try:
                topics.append(TopicStats.from_dict(json.loads(value)))
            except Exception:
                continue
        return topics

    async def get_all_messages(self) -> List[dict]:
        """Get all message records."""
        data = await self._get_all(self.MESSAGES_NAME)
        messages = []
        for key, value in data.items():
            try:
                messages.append(json.loads(value))
            except Exception:
                continue
        return messages

    async def get_stats_by_period(self, days: int | None = None) -> dict:
        """
        Get statistics for a given period.

        Returns:
        - new_topics: количество новых топиков за период
        - active_topics: количество топиков с активностью за период
        - total_messages: общее количество сообщений от пользователей
        - responder_stats: {responder_id: {unique_topics: N, total_messages: M, name: str}}
        """
        topics = await self.get_all_topics()
        messages = await self.get_all_messages()

        now = datetime.now(timezone(timedelta(hours=3)))
        if days:
            cutoff = now - timedelta(days=days)
        else:
            cutoff = None

        new_topics = 0
        active_topics = 0
        total_user_messages = 0
        responder_stats: Dict[str, dict] = {}

        for topic in topics:
            try:
                created = datetime.strptime(topic.created_at, "%Y-%m-%d %H:%M:%S")
                created = created.replace(tzinfo=timezone(timedelta(hours=3)))
                updated = datetime.strptime(topic.updated_at, "%Y-%m-%d %H:%M:%S")
                updated = updated.replace(tzinfo=timezone(timedelta(hours=3)))
            except Exception:
                continue

            if cutoff is None or created >= cutoff:
                new_topics += 1

            if cutoff is None or updated >= cutoff:
                active_topics += 1
                total_user_messages += topic.total_messages

        # Считаем статистику респондентов за период
        for msg in messages:
            try:
                timestamp = datetime.strptime(msg["timestamp"], "%Y-%m-%d %H:%M:%S")
                timestamp = timestamp.replace(tzinfo=timezone(timedelta(hours=3)))
            except Exception:
                continue

            if cutoff is not None and timestamp < cutoff:
                continue

            responder_id = str(msg["responder_id"])
            responder_name = msg.get("responder_name", "Unknown")
            thread_id = msg["message_thread_id"]

            if responder_id not in responder_stats:
                responder_stats[responder_id] = {
                    "name": responder_name,
                    "unique_topics": set(),
                    "total_messages": 0,
                }

            responder_stats[responder_id]["unique_topics"].add(thread_id)
            responder_stats[responder_id]["total_messages"] += 1

        # Конвертируем set в count
        for resp_id in responder_stats:
            responder_stats[resp_id]["unique_topics"] = len(responder_stats[resp_id]["unique_topics"])

        return {
            "new_topics": new_topics,
            "active_topics": active_topics,
            "total_user_messages": total_user_messages,
            "responder_stats": responder_stats,
        }

    async def export_topics_csv(
        self,
        days: int | None = None,
        admin_ids: set[int] | None = None,
        admin_names: dict[int, str] | None = None,
    ) -> str:
        """Export topics to CSV format with per-admin response columns."""
        topics = await self.get_all_topics()

        now = datetime.now(timezone(timedelta(hours=3)))
        if days:
            cutoff = now - timedelta(days=days)
        else:
            cutoff = None

        # Формируем заголовок: если есть admin_ids — по столбцу на админа, иначе — старый формат
        sorted_admin_ids = sorted(admin_ids) if admin_ids else []
        if sorted_admin_ids and admin_names:
            admin_columns = [admin_names.get(aid, str(aid)).replace(",", " ").replace('"', "'") for aid in sorted_admin_ids]
            header = "user_id,user_name,username,topic_link,created_at,updated_at,total_messages," + ",".join(f'"{col}"' for col in admin_columns)
        else:
            header = "user_id,user_name,username,topic_link,created_at,updated_at,total_messages,responders"

        lines = [header]

        for topic in topics:
            try:
                updated = datetime.strptime(topic.updated_at, "%Y-%m-%d %H:%M:%S")
                updated = updated.replace(tzinfo=timezone(timedelta(hours=3)))
            except Exception:
                continue

            if cutoff is not None and updated < cutoff:
                continue

            # Экранируем запятые в имени
            user_name = topic.user_name.replace(",", " ").replace('"', "'")
            username = (topic.username or "-").replace(",", " ")

            base = f'{topic.user_id},"{user_name}",{username},{topic.topic_link},{topic.created_at},{topic.updated_at},{topic.total_messages}'

            if sorted_admin_ids and admin_names:
                # По столбцу на каждого админа
                counts = [str(topic.responder_counts.get(str(aid), 0)) for aid in sorted_admin_ids]
                line = base + "," + ",".join(counts)
            else:
                responders = "; ".join([f"{k}:{v}" for k, v in topic.responder_counts.items()])
                line = base + f',"{responders}"'

            lines.append(line)

        return "\n".join(lines)

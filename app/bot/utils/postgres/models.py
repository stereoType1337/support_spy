from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta


@dataclass
class UserData:
    """Data class representing user information."""
    message_thread_id: int | None
    message_silent_id: int | None
    message_silent_mode: bool

    id: int
    full_name: str
    username: str | None
    state: str = "member"
    is_banned: bool = False
    language_code: str | None = None
    created_at: str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S %Z")
    has_sent_message: bool = False
    has_bot_replied: bool = False
    is_bot_stopped: bool = False
    is_bot_restarted: bool = False
    source_bot_id: int | None = None

    def to_dict(self) -> dict:
        """
        Converts UserData object to a dictionary.

        :return: Dictionary representation of UserData.
        """
        return asdict(self)

from dataclasses import dataclass

from environs import Env


def parse_admin_ids(raw: str) -> set[int]:
    if not raw:
        return set()
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return {int(p) for p in parts}


@dataclass
class BotConfig:

    TOKEN: str
    DEV_IDS: set[int]
    GROUP_ID: int
    BOT_EMOJI_ID: str
    ADMIN_IDS: set[int]
    TOPICS_CHAT_ID: int | None
    TOPICS_THREAD_ID: int | None


@dataclass
class PostgresConfig:
    HOST: str
    PORT: int
    DB: str
    USER: str
    PASSWORD: str

    def dsn(self) -> str:
        return f"postgresql://{self.USER}:{self.PASSWORD}@{self.HOST}:{self.PORT}/{self.DB}"


@dataclass
class NotspyConfig:
    URL: str
    TOKEN: str
    BOT_USERNAME: str

    @property
    def enabled(self) -> bool:
        return bool(self.URL and self.TOKEN)


@dataclass
class Config:
    bot: BotConfig
    postgres: PostgresConfig
    notspy: NotspyConfig


def load_config() -> Config:
    env = Env()
    env.read_env()

    admin_ids_raw = env.str("BOT_ADMIN_IDS", default="")

    return Config(
        bot=BotConfig(
            TOKEN=env.str("BOT_TOKEN"),
            DEV_IDS=parse_admin_ids(env.str("BOT_DEV_ID")),
            GROUP_ID=env.int("BOT_GROUP_ID"),
            BOT_EMOJI_ID=env.str("BOT_EMOJI_ID"),
            ADMIN_IDS=parse_admin_ids(admin_ids_raw),
            TOPICS_CHAT_ID=env.int("TOPICS_CHAT_ID", default=None),
            TOPICS_THREAD_ID=env.int("TOPICS_THREAD_ID", default=None),
        ),
        postgres=PostgresConfig(
            HOST=env.str("POSTGRES_HOST"),
            PORT=env.int("POSTGRES_PORT", 5432),
            DB=env.str("POSTGRES_DB"),
            USER=env.str("POSTGRES_USER"),
            PASSWORD=env.str("POSTGRES_PASSWORD"),
        ),
        notspy=NotspyConfig(
            URL=env.str("NOTSPY_API_URL", default="").rstrip("/"),
            TOKEN=env.str("NOTSPY_API_TOKEN", default=""),
            BOT_USERNAME=env.str("NOTSPY_BOT_USERNAME", default="notspybotbot"),
        ),
    )

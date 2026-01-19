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
    DEV_ID: int
    GROUP_ID: int
    BOT_EMOJI_ID: str
    ADMIN_IDS: set[int]  # <-- NEW


@dataclass
class RedisConfig:
    HOST: str
    PORT: int
    DB: int

    def dsn(self) -> str:
        return f"redis://{self.HOST}:{self.PORT}/{self.DB}"


@dataclass
class ApiConfig:
    URL: str
    TOKEN: str
    ADMIN_TG_ID: int
    BOT_USERNAME: str


@dataclass
class Config:
    bot: BotConfig
    redis: RedisConfig
    api: ApiConfig


def load_config() -> Config:
    env = Env()
    env.read_env()

    admin_ids_raw = env.str("BOT_ADMIN_IDS", default="")

    return Config(
        bot=BotConfig(
            TOKEN=env.str("BOT_TOKEN"),
            DEV_ID=env.int("BOT_DEV_ID"),
            GROUP_ID=env.int("BOT_GROUP_ID"),
            BOT_EMOJI_ID=env.str("BOT_EMOJI_ID"),
            ADMIN_IDS=parse_admin_ids(admin_ids_raw),
        ),
        redis=RedisConfig(
            HOST=env.str("REDIS_HOST"),
            PORT=env.int("REDIS_PORT"),
            DB=env.int("REDIS_DB"),
        ),
        api=ApiConfig(
            URL=env.str("API_URL", default="https://bot.raytun.ru/api"),
            TOKEN=env.str("API_TOKEN"),
            ADMIN_TG_ID=env.int("API_ADMIN_TG_ID"),
            BOT_USERNAME=env.str("BOT_USERNAME", default="vpn_plus777_bot"),
        ),
    )

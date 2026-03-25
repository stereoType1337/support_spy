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
class PostgresConfig:
    HOST: str
    PORT: int
    DB: str
    USER: str
    PASSWORD: str

    def dsn(self) -> str:
        return f"postgresql://{self.USER}:{self.PASSWORD}@{self.HOST}:{self.PORT}/{self.DB}"


@dataclass
class RemnaConfig:
    URL: str
    TOKEN: str


@dataclass
class ApiConfig:
    URL: str
    TOKEN: str
    ADMIN_TG_ID: int
    BOT_USERNAME: str


@dataclass
class Config:
    bot: BotConfig
    postgres: PostgresConfig
    api: ApiConfig
    remna: RemnaConfig


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
        postgres=PostgresConfig(
            HOST=env.str("POSTGRES_HOST"),
            PORT=env.int("POSTGRES_PORT", 5432),
            DB=env.str("POSTGRES_DB"),
            USER=env.str("POSTGRES_USER"),
            PASSWORD=env.str("POSTGRES_PASSWORD"),
        ),
        api=ApiConfig(
            URL=env.str("API_URL", default="https://bot.raytun.ru/api"),
            TOKEN=env.str("API_TOKEN"),
            ADMIN_TG_ID=env.int("API_ADMIN_TG_ID"),
            BOT_USERNAME=env.str("BOT_USERNAME", default="vpn_plus777_bot"),
        ),
        remna=RemnaConfig(
            URL=env.str("REMNA_URL", default=""),
            TOKEN=env.str("REMNA_TOKEN", default=""),
        ),
    )

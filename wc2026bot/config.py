import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    bot_token: str
    db_path: str
    footballdata_key: str | None


def load_settings() -> Settings:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable is required")
    return Settings(
        bot_token=token,
        db_path=os.environ.get("DB_PATH", "wc2026.db"),
        footballdata_key=os.environ.get("FOOTBALLDATA_KEY") or None,
    )

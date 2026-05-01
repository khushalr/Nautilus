import json
from functools import lru_cache

from pydantic import AliasChoices, AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Nautilus"
    environment: str = "local"
    database_url: str = Field(
        default="postgresql+psycopg://nautilus:nautilus@postgres:5432/nautilus",
        alias="DATABASE_URL",
    )
    frontend_origin: str = Field(default="http://localhost:3000", alias="FRONTEND_ORIGIN")
    public_app_url: str = Field(default="http://localhost:3000", alias="PUBLIC_APP_URL")
    alert_cooldown_minutes: int = Field(default=60, alias="ALERT_COOLDOWN_MINUTES")

    polymarket_api_url: AnyUrl = Field(
        default="https://gamma-api.polymarket.com",
        alias="POLYMARKET_API_URL",
    )

    kalshi_api_url: AnyUrl = Field(
        default="https://trading-api.kalshi.com/trade-api/v2",
        alias="KALSHI_API_URL",
    )
    kalshi_api_key: str | None = Field(default=None, alias="KALSHI_API_KEY")
    kalshi_api_secret: str | None = Field(default=None, alias="KALSHI_API_SECRET")

    odds_api_url: AnyUrl = Field(
        default="https://api.the-odds-api.com/v4",
        validation_alias=AliasChoices("THE_ODDS_API_URL", "ODDS_API_URL"),
    )
    the_odds_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("THE_ODDS_API_KEY", "ODDS_API_KEY"),
    )
    sports_to_collect_raw: str = Field(
        default="americanfootball_nfl,basketball_nba,baseball_mlb,icehockey_nhl",
        alias="SPORTS_TO_COLLECT",
    )
    sportsbook_markets_to_collect_raw: str = Field(
        default="h2h,outrights",
        alias="SPORTSBOOK_MARKETS_TO_COLLECT",
    )
    smtp_host: str | None = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str | None = Field(default=None, alias="SMTP_USERNAME")
    smtp_password: str | None = Field(default=None, alias="SMTP_PASSWORD")
    alert_email_from: str | None = Field(default=None, alias="ALERT_EMAIL_FROM")
    alert_email_to: str | None = Field(default=None, alias="ALERT_EMAIL_TO")
    odds_api_low_quota_threshold: int = Field(default=50, alias="ODDS_API_LOW_QUOTA_THRESHOLD")
    odds_api_quota_email_cooldown_hours: int = Field(default=6, alias="ODDS_API_QUOTA_EMAIL_COOLDOWN_HOURS")
    odds_api_quota_state_file: str = Field(default="/tmp/nautilus_odds_api_quota_email.json", alias="ODDS_API_QUOTA_STATE_FILE")

    default_user_model: dict[str, object] = {
        "min_edge": 0.03,
        "max_spread": 0.06,
        "min_liquidity": 500,
        "spread_penalty_multiplier": 0.5,
        "liquidity_penalty_multiplier": 0.02,
        "bookmaker_weights": {
            "draftkings": 1.0,
            "fanduel": 1.0,
            "betmgm": 0.9,
            "caesars": 0.9,
            "pinnacle": 1.2,
        },
        "excluded_bookmakers": [],
    }

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def sports_to_collect(self) -> list[str]:
        if self.sports_to_collect_raw.strip().startswith("["):
            try:
                parsed = json.loads(self.sports_to_collect_raw)
            except json.JSONDecodeError:
                parsed = []
            if isinstance(parsed, list):
                return [str(sport).strip() for sport in parsed if str(sport).strip()]
        return [sport.strip() for sport in self.sports_to_collect_raw.split(",") if sport.strip()]

    @property
    def sportsbook_markets_to_collect(self) -> list[str]:
        aliases = {"moneyline": "h2h", "h2h_game": "h2h"}
        markets: list[str] = []
        for market in [
            aliases.get(market.strip().lower(), market.strip().lower())
            for market in self.sportsbook_markets_to_collect_raw.split(",")
            if market.strip()
        ]:
            if market in {"h2h", "outrights"} and market not in markets:
                markets.append(market)
        return markets


@lru_cache
def get_settings() -> Settings:
    return Settings()

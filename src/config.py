from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    serper_api_key: str

    # Search behaviour
    max_results: int = 30
    max_serper_queries_per_search: int = 8

    # Timeouts
    ats_request_timeout_seconds: int = 5
    scraper_request_timeout_seconds: int = 10
    search_hard_timeout_seconds: int = 30

    # Nigerian scraper politeness
    scraper_delay_seconds: float = 1.5

    # In-memory cache
    cache_ttl_seconds: int = 300  # 5 minutes

    # Rate limiting
    rate_limit_per_hour: int = 20  # per IP

    # Subscriptions
    subscriptions_file: str = "subscriptions.csv"

    log_level: str = "INFO"


settings = Settings()

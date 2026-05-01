from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./payroll_dev.db"
    jwt_secret: str = "change-me-in-production-use-long-random-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    # Comma-separated browser origins (Next app). Production default: peopleopslab.in + www;
    # API itself is served at api.peopleopslab.in. Override with CORS_ORIGINS if the app host differs.
    cors_origins: str = (
        "http://localhost:3000,https://peopleopslab.in,"
        "https://www.peopleopslab.in"
    )
    # When True, requests without Bearer token use the built-in system user (local dev convenience).
    # Set False in production to require JWT on all protected routes.
    allow_anonymous_api: bool = True

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

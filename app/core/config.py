from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://nexustalent:nexustalent@localhost:5432/nexustalent"

    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "neo4jpassword"

    QDRANT_URL: str = "http://localhost:6333"
    REDIS_URL: str = "redis://localhost:6379/0"

    # No default: a forgeable, publicly-known secret would let anyone mint valid
    # tokens. Must be set via env/.env, or Settings() raises at startup.
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    GEMINI_API_KEY: str | None = None

    CV_STORAGE_DIR: str = "storage/cvs"

    # Comma-separated list of allowed frontend origins. No wildcard: it cannot be
    # combined with allow_credentials=True (browsers reject it, and it would allow
    # any site to call the API with a logged-in user's credentials).
    CORS_ORIGINS: str = "http://localhost:3000"

    # Off by default in tests (see tests/conftest.py) so suites that log in
    # repeatedly don't trip the /auth/login limit; on everywhere else.
    RATE_LIMIT_ENABLED: bool = True

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()

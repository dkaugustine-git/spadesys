from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://spadesys:spadesys@localhost:5432/spadesys"

    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "spadesys"
    s3_secret_key: str = "spadesys-secret"
    s3_bucket: str = "landing"

    meta_schema: str = "spadesys"  # Spadesys's own bookkeeping
    raw_schema: str = "raw"  # landed source data
    clean_schema: str = "clean"  # what transforms write

    worker_poll_seconds: float = 2.0
    max_upload_mb: int = 200
    inbox_dir: str = "/data/inbox"  # pipeline folders; ./data/inbox on your computer


@lru_cache
def get_settings() -> Settings:
    return Settings()

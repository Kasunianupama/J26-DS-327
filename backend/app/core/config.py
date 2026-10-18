from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    frontend_url: str = "http://localhost:5173"
    # App database (farmx_app, PostgreSQL). The backend logs in as the
    # least-privilege role farmx_api; it never connects to DelPro / SQL Server.
    app_db_host: str = "localhost"
    app_db_port: int = 5433
    app_db_name: str = "farmx_app"
    app_db_api_user: str = "farmx_api"
    app_db_api_password: str = ""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
